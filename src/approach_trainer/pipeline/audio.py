"""Audio-cache helpers: extract a 16 kHz mono flac per video for Scribe.

The flac lives in ``AUDIO_CACHE`` keyed by a hash of the video path. It is purely
transient — needed only while the 5 Scribe passes run; the factory deletes it once
the clip is finalized (``drop_cache``). Re-derivable from the video at any time.
"""

from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from approach_trainer.paths import AUDIO_CACHE

if TYPE_CHECKING:
    from pathlib import Path

EXTRACT_TIMEOUT = 600


def fid_of(path: Path) -> str:
    """Stable content-cache key for a video path (md5 of the path string)."""
    return hashlib.md5(str(path).encode()).hexdigest()


def flac_path(video: Path) -> Path:
    return AUDIO_CACHE / f"{fid_of(video)}.flac"


def extract_audio(video: Path) -> Path | None:
    """Extract a 16 kHz mono flac for ``video`` into the cache; return its path."""
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    flac = flac_path(video)
    if not flac.exists():
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(video),
                 "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(flac)],
                check=False, timeout=EXTRACT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0:
            return None
    return flac


def drop_cache(video: Path) -> None:
    """Delete the cached flac for a video (called after the clip is finalized)."""
    flac_path(video).unlink(missing_ok=True)
