"""Registry-driven YouTube downloading for Approach Trainer."""

from __future__ import annotations

import fcntl
import os
import shlex
import subprocess
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from superwhisper_api.languages import resolve

from approach_trainer.paths import (
    DATA_DIR,
    DEFAULT_MEDIA_ROOT,
    DEFAULT_YOUTUBE_CONFIG,
    PROJECT_ROOT,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov"}


@dataclass(frozen=True, slots=True)
class BrowserProfile:
    name: str
    browser: str
    path: Path
    lock: Path
    sleep_requests: float
    sleep_interval: float

    @property
    def browser_spec(self) -> str:
        return f"{self.browser}:{self.path}"


@dataclass(frozen=True, slots=True)
class YoutubeChannel:
    slug: str
    url: str
    group: str
    language: str
    profile: str
    note: str


@dataclass(frozen=True, slots=True)
class YoutubeRegistry:
    media_root: Path
    video_format: str
    player_client: str
    factory_trigger: Path
    profiles: dict[str, BrowserProfile]
    channels: tuple[YoutubeChannel, ...]

    def channel_by_slug(self, slug: str) -> YoutubeChannel:
        for channel in self.channels:
            if channel.slug == slug:
                return channel
        msg = f"unknown channel slug: {slug}"
        raise KeyError(msg)

    def selected(
        self,
        *,
        slug: str | None = None,
        group: str | None = None,
        language: str | None = None,
    ) -> list[YoutubeChannel]:
        channels = list(self.channels)
        if slug is not None:
            channels = [self.channel_by_slug(slug)]
        if group is not None:
            channels = [channel for channel in channels if channel.group == group]
        if language is not None:
            channels = [channel for channel in channels if channel.language == language]
        return channels


@dataclass(frozen=True, slots=True)
class DownloadResult:
    channel: YoutubeChannel
    out_dir: Path
    media_count: int


def load_registry(path: Path = DEFAULT_YOUTUBE_CONFIG) -> YoutubeRegistry:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    settings = _mapping(raw.get("settings", {}), "settings")
    profiles_raw = _mapping(raw.get("profiles", {}), "profiles")
    channels_raw = _list(raw.get("channels", []), "channels")

    media_root = Path(str(settings.get("media_root", DEFAULT_MEDIA_ROOT))).expanduser()
    factory_trigger = Path(
        str(settings.get("factory_trigger", PROJECT_ROOT / "bin" / "factory_trigger.sh"))
    ).expanduser()

    profiles = {
        name: _profile_from_raw(name, _mapping(value, f"profiles.{name}"))
        for name, value in profiles_raw.items()
    }
    channels = tuple(
        _channel_from_raw(_mapping(value, f"channels[{index}]"))
        for index, value in enumerate(channels_raw)
    )
    _validate_registry(profiles, channels)

    return YoutubeRegistry(
        media_root=media_root,
        video_format=str(settings.get("format", "bv*[height<=1920]+ba/b[height<=1920]/b")),
        player_client=str(settings.get("player_client", "web_safari")),
        factory_trigger=factory_trigger,
        profiles=profiles,
        channels=channels,
    )


def download_channels(
    registry: YoutubeRegistry,
    channels: list[YoutubeChannel],
    *,
    profile_override: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    run_factory: bool = True,
) -> list[DownloadResult]:
    results: list[DownloadResult] = []
    for channel in channels:
        profile_name = profile_override or channel.profile
        profile = registry.profiles[profile_name]
        with profile_lock(profile):
            results.append(
                download_channel(
                    registry,
                    channel,
                    profile,
                    limit=limit,
                    dry_run=dry_run,
                )
            )

    if run_factory and not dry_run and results:
        subprocess.Popen(
            ["/usr/bin/bash", str(registry.factory_trigger)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return results


def download_channel(
    registry: YoutubeRegistry,
    channel: YoutubeChannel,
    profile: BrowserProfile,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> DownloadResult:
    # Layout: yt/<2-letter-lang>/<creator>/ — strip any "<lang>-" prefix the slug carries.
    lang2 = resolve(channel.language).iso639_1 or channel.language
    creator = channel.slug.removeprefix(f"{lang2}-")
    out_dir = registry.media_root / "yt" / lang2 / creator
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--cookies-from-browser",
        profile.browser_spec,
        "--extractor-args",
        f"youtube:player_client={registry.player_client}",
        "-f",
        registry.video_format,
        "--fragment-retries",
        "5",
        "--download-archive",
        str(out_dir / ".archive.txt"),
        "--sleep-requests",
        str(profile.sleep_requests),
        "--sleep-interval",
        str(profile.sleep_interval),
        "--ignore-errors",
        "-o",
        str(out_dir / "%(id)s.%(ext)s"),
    ]
    if limit is not None:
        cmd.extend(["--playlist-end", str(limit)])
    cmd.append(channel.url)

    if dry_run:
        print(shlex.join(cmd))
    else:
        subprocess.run(cmd, check=False)
    return DownloadResult(channel=channel, out_dir=out_dir, media_count=count_media(out_dir))


def refresh_cookies(profile: BrowserProfile, out_path: Path | None = None) -> tuple[Path, int]:
    out = out_path or DATA_DIR / "youtube" / f"{profile.name}.cookies.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--cookies-from-browser",
        profile.browser_spec,
        "--cookies",
        str(out),
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    ]
    subprocess.run(cmd, check=False)
    count = 0
    if out.exists():
        count = sum(
            1
            for line in out.read_text(encoding="utf-8").splitlines()
            if "youtube.com" in line and not line.startswith("#")
        )
    return out, count


def count_media(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1
        for child in path.iterdir()
        if child.is_file() and child.suffix.lower() in VIDEO_SUFFIXES
    )


@contextmanager
def profile_lock(profile: BrowserProfile) -> Iterator[None]:
    profile.lock.parent.mkdir(parents=True, exist_ok=True)
    with profile.lock.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _profile_from_raw(name: str, raw: dict[str, Any]) -> BrowserProfile:
    return BrowserProfile(
        name=name,
        browser=str(raw["browser"]),
        path=Path(os.path.expandvars(str(raw["path"]))).expanduser(),
        lock=Path(os.path.expandvars(str(raw["lock"]))).expanduser(),
        sleep_requests=float(raw.get("sleep_requests", 2.0)),
        sleep_interval=float(raw.get("sleep_interval", 3.0)),
    )


def _channel_from_raw(raw: dict[str, Any]) -> YoutubeChannel:
    return YoutubeChannel(
        slug=str(raw["slug"]),
        url=str(raw["url"]),
        group=str(raw["group"]),
        language=str(raw["language"]),
        profile=str(raw["profile"]),
        note=str(raw.get("note", "")),
    )


def _validate_registry(
    profiles: dict[str, BrowserProfile],
    channels: tuple[YoutubeChannel, ...],
) -> None:
    seen: set[str] = set()
    duplicate_slugs: set[str] = set()
    for channel in channels:
        if channel.slug in seen:
            duplicate_slugs.add(channel.slug)
        seen.add(channel.slug)
    if duplicate_slugs:
        msg = f"duplicate channel slugs: {', '.join(sorted(duplicate_slugs))}"
        raise ValueError(msg)
    missing_profiles = sorted({channel.profile for channel in channels} - set(profiles))
    if missing_profiles:
        msg = f"channels reference unknown profiles: {', '.join(missing_profiles)}"
        raise ValueError(msg)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        msg = f"{name} must be a table"
        raise TypeError(msg)
    return cast("dict[str, Any]", value)


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        msg = f"{name} must be a list"
        raise TypeError(msg)
    return cast("list[Any]", value)
