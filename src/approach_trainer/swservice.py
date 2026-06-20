"""Local client for the deployed superwhisper-api HTTP service (text + ASR).

A thin httpx client for the deployed service at ``SUPERWHISPER_API_BASE`` (authenticated with
a ``sw_live_…`` bearer key). It replaces the old in-process ``superwhisper_api`` package: there
is no cached signed credential, no ElevenLabs key rotation, and no local ASR worker here — the
service owns all of that.

Two surfaces:

- :class:`SuperwhisperClient` — text/LLM generation (``generate`` / ``generate_json``),
  mirroring jobkit / omni-curator's client so the segment / speaker / fuse call sites keep
  their shape. ``messages`` is first; ``model`` is a keyword. ``generate`` returns a ``str``.
- :func:`transcribe_file` — submit one audio file to the async ASR endpoint and poll to
  completion, returning the job ``result`` dict (read ``result["transcript"]`` and, when
  ``detail`` is requested, ``result["words"]`` / ``result["turns"]``).

Config comes from the environment (or the nearest ``.env`` walking up from this file):
``SUPERWHISPER_API_BASE`` (e.g. ``https://superwhisper.peacockery.studio``) and
``SUPERWHISPER_API_KEY`` (the ``sw_live_…`` bearer key).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Default text model; the deployed service exposes the same model registry as before.
MODEL_ID = "claude-sonnet-4-6"
_GENERATE_PATH = "/v1/text/generate"
_TRANSCRIBE_PATH = "/v1/transcriptions"
_JOB_PATH = "/v1/jobs"
_TIMEOUT = 120.0
#: How long to keep polling a submitted ASR job before giving up.
_ASR_POLL_TIMEOUT = 1800.0
#: Seconds between ASR job-status polls.
_ASR_POLL_INTERVAL = 2.0


def parse_json_text(text: str) -> object:
    """Parse the first JSON value in a model response.

    Tolerates ```json fences, prose before the value ("Here is the JSON: {..."), and
    trailing text after it (the "Extra data" failure mode) — models add all three in
    practice.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    starts = [i for i in (stripped.find("{"), stripped.find("[")) if i != -1]
    value, _end = json.JSONDecoder().raw_decode(stripped, min(starts) if starts else 0)
    return value


def _load_env_file(start: Path) -> dict[str, str]:
    """Best-effort parse of the nearest ``.env`` (``KEY=VALUE``) walking up from ``start``."""
    for directory in (start, *start.parents):
        env_path = directory / ".env"
        if not env_path.is_file():
            continue
        values: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values
    return {}


def _resolve_target() -> tuple[str, str]:
    """Return ``(base_url, api_key)`` from the environment, falling back to a ``.env``."""
    base = os.environ.get("SUPERWHISPER_API_BASE")
    key = os.environ.get("SUPERWHISPER_API_KEY")
    if not base or not key:
        fallback = _load_env_file(Path(__file__).resolve().parent)
        base = base or fallback.get("SUPERWHISPER_API_BASE")
        key = key or fallback.get("SUPERWHISPER_API_KEY")
    if not base or not key:
        msg = (
            "SUPERWHISPER_API_BASE and SUPERWHISPER_API_KEY must be set "
            "(in the environment or a .env file)."
        )
        raise RuntimeError(msg)
    return base.rstrip("/"), key


def _make_client() -> httpx.Client:
    """Build an httpx client bound to the service base URL + bearer key."""
    base, key = _resolve_target()
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {key}"},
        timeout=_TIMEOUT,
    )


class SuperwhisperClient:
    """Text generation via the deployed superwhisper-api HTTP service."""

    def __init__(self, *, model: str = MODEL_ID) -> None:
        """Build the client, resolving the service base URL + bearer key."""
        self._model = model
        self._client = _make_client()

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        model: str | None = None,
        system: str | None = None,
        response_format: dict[str, object] | None = None,
    ) -> str:
        """Return the model's text for a chat ``messages`` list.

        ``system`` is an optional system prompt; ``response_format`` is passed through to the
        service (it does not enforce schemas, so :meth:`generate_json` still parses the text).
        """
        payload: dict[str, object] = {
            "model": model or self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system is not None:
            payload["system"] = system
        if response_format is not None:
            payload["response_format"] = response_format
        response = self._client.post(_GENERATE_PATH, json=payload)
        response.raise_for_status()
        return str(response.json()["text"])

    def generate_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        model: str | None = None,
        system: str | None = None,
        response_format: dict[str, object] | None = None,
    ) -> object:
        """Return the model's response parsed as JSON (the service does not enforce schemas)."""
        return parse_json_text(
            self.generate(
                messages,
                max_tokens=max_tokens,
                model=model,
                system=system,
                response_format=response_format,
            )
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        """Enter a context manager, returning ``self``."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Exit the context manager, closing the HTTP client."""
        self.close()


def transcribe_file(
    path: str | Path,
    *,
    asr_model: str = "scribe-v2",
    mode: str = "single",
    language: str | None = None,
    diarize: bool = False,
    detail: Sequence[str] | None = None,
    workers: int | None = None,
    poll_interval: float = _ASR_POLL_INTERVAL,
    poll_timeout: float = _ASR_POLL_TIMEOUT,
) -> dict[str, object]:
    """Transcribe one local audio file through the deployed ASR service; return its ``result``.

    Submits ``path`` (resolved to an absolute path the service can read off its read-only
    ``/home/simon`` + ``/mnt`` mounts) to ``POST /v1/transcriptions`` and polls
    ``GET /v1/jobs/{job_id}`` until the job succeeds. Returns the job ``result`` dict, so the
    caller reads ``result["transcript"]`` (and ``result["words"]`` / ``result["turns"]`` when
    ``detail`` is requested). ``mode`` is ``"single"`` (one pass) or ``"consensus"`` (ensemble
    + fuse). ``language=None`` lets the service auto-detect / code-switch.

    Raises :class:`RuntimeError` if the job fails or does not finish within ``poll_timeout``.
    The service owns ASR key rotation, so there is no key handling here.
    """
    payload: dict[str, object] = {
        "input": str(Path(path).resolve()),
        "asr_model": asr_model,
        "mode": mode,
    }
    if language is not None:
        payload["language"] = language
    if diarize:
        payload["diarize"] = True
    if detail is not None:
        payload["detail"] = list(detail)
    if workers is not None:
        payload["workers"] = workers

    with _make_client() as client:
        submit = client.post(_TRANSCRIBE_PATH, json=payload)
        submit.raise_for_status()
        job_id = str(submit.json()["job_id"])
        return _poll_job(client, job_id, interval=poll_interval, timeout=poll_timeout)


def _poll_job(
    client: httpx.Client, job_id: str, *, interval: float, timeout: float
) -> dict[str, object]:
    """Poll ``GET /v1/jobs/{job_id}`` until it succeeds; raise on failure or timeout."""
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"{_JOB_PATH}/{job_id}")
        response.raise_for_status()
        body = response.json()
        status = body.get("status")
        if status == "succeeded":
            result = body.get("result")
            if not isinstance(result, dict):
                msg = f"job {job_id} succeeded but returned no result"
                raise RuntimeError(msg)
            return result
        if status == "failed":
            msg = f"transcription job {job_id} failed: {body.get('error')}"
            raise RuntimeError(msg)
        if time.monotonic() >= deadline:
            msg = (
                f"transcription job {job_id} did not finish within "
                f"{timeout:.0f}s (status={status})"
            )
            raise RuntimeError(msg)
        time.sleep(interval)
