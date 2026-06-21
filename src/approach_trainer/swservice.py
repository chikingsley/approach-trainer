"""Local client for the deployed superwhisper-api HTTP service (text + ASR).

A thin httpx client for the deployed service at ``SUPERWHISPER_API_BASE`` (authenticated with
a ``sw_live_…`` bearer key). It replaces the old in-process ``superwhisper_api`` package: there
is no cached signed credential, no ElevenLabs key rotation, and no local ASR worker here — the
service owns all of that.

Two surfaces:

- :class:`SuperwhisperClient` — text/LLM generation (``generate`` / ``generate_json``),
  mirroring jobkit / omni-curator's client so the segment / speaker / fuse call sites keep
  their shape. ``messages`` is first; ``model`` is a keyword. ``generate`` returns a ``str``.
- :func:`transcribe_file` — post one audio file to the synchronous ASR endpoint and
  return the result dict inline (read ``result["transcript"]`` and, when ``detail`` is
  requested, ``result["words"]`` / ``result["turns"]``).

Config comes from the environment (or the nearest ``.env`` walking up from this file):
``SUPERWHISPER_API_BASE`` (e.g. ``https://superwhisper.peacockery.studio``) and
``SUPERWHISPER_API_KEY`` (the ``sw_live_…`` bearer key).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Self

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Default text model; the deployed service exposes the same model registry as before.
MODEL_ID = "claude-sonnet-4-6"
_GENERATE_PATH = "/v1/text/generate"
_TRANSCRIBE_PATH = "/v1/transcriptions"
_TIMEOUT = 120.0


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
    mode: str = "single",  # noqa: ARG001  # accepted for back-compat; consensus now lives at /v1/transcriptions/consensus
    language: str | None = None,
    diarize: bool = False,
    detail: Sequence[str] | None = None,
    timestamps: bool = False,
    formats: Sequence[str] | None = None,
    workers: int | None = None,  # noqa: ARG001  # accepted for back-compat; the sync endpoint has no worker fan-out
) -> dict[str, object]:
    """Transcribe one local audio file through the deployed ASR service; return its result.

    Posts ``path`` (resolved to an absolute path the service can read off its read-only
    ``/home/simon`` + ``/mnt`` mounts) to the synchronous ``POST /v1/transcriptions`` and
    returns the result dict inline (no job / no poll). The caller reads
    ``result["transcript"]`` (and ``result["words"]`` / ``result["turns"]`` when ``detail`` is
    requested). ``language=None`` lets the service auto-detect / code-switch.
    ``timestamps=True`` makes the returned ``words`` (and ``turns``) carry ``start`` / ``end``
    offsets.

    Raises for any non-2xx response. The service owns ASR key rotation, so there is no key
    handling here.
    """
    payload: dict[str, object] = {
        "input": str(Path(path).resolve()),
        "asr_model": asr_model,
    }
    if language is not None:
        payload["language"] = language
    if diarize:
        payload["diarize"] = True
    if detail is not None:
        payload["detail"] = list(detail)
    if timestamps:
        payload["timestamps"] = True
    if formats is not None:
        payload["formats"] = list(formats)

    with _make_client() as client:
        response = client.post(_TRANSCRIBE_PATH, json=payload)
        response.raise_for_status()
        return dict(response.json())
