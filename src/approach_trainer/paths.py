"""Shared filesystem anchors for local Approach Trainer workflows."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_MEDIA_ROOT = Path("/mnt/media/gmk-server-share/approach-clips")
DEFAULT_YOUTUBE_CONFIG = CONFIG_DIR / "youtube_channels.toml"

# Pipeline anchors
CLIPS_ROOT = DEFAULT_MEDIA_ROOT
COURSES_ROOT = Path("/mnt/media/pickup-courses")
AUDIO_CACHE = DEFAULT_MEDIA_ROOT / "factory-audio"  # transient flacs, deleted after finalize
DEFAULT_DB = DATA_DIR / "clips.db"
