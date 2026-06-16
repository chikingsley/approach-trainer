"""Command-line entry points for Approach Trainer."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from approach_trainer.ingest.youtube import (
    YoutubeRegistry,
    download_channels,
    load_registry,
    refresh_cookies,
)

# Pipeline steps keep their own argparse main(); the CLI forwards the remaining argv
# so `approach-trainer factory <db> …` runs the same code as
# `python -m approach_trainer.pipeline.factory <db> …`. Maps command -> module.
PIPELINE_STEPS = {
    "factory": "approach_trainer.pipeline.factory",
    "segment": "approach_trainer.pipeline.segment",
    "cuts": "approach_trainer.pipeline.cuts",
    "durations": "approach_trainer.pipeline.durations",
    "retag": "approach_trainer.pipeline.retag",
    "speaker-identity": "approach_trainer.pipeline.speaker_identity",
    "instagram": "approach_trainer.ingest.instagram",
}


def _run_step(command: str, rest: list[str]) -> int:
    module = importlib.import_module(PIPELINE_STEPS[command])
    saved = sys.argv
    sys.argv = [f"approach-trainer {command}", *rest]
    try:
        result = module.main()
    finally:
        sys.argv = saved
    return result if isinstance(result, int) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="approach-trainer")
    parser.add_argument("--config", type=Path, help="youtube channel registry TOML")
    subparsers = parser.add_subparsers(dest="command", required=True)

    youtube = subparsers.add_parser("youtube", help="YouTube source operations")
    youtube_sub = youtube.add_subparsers(dest="youtube_command", required=True)

    list_parser = youtube_sub.add_parser("list", help="list registered channels")
    list_parser.add_argument("--group")
    list_parser.add_argument("--language")

    profiles_parser = youtube_sub.add_parser("profiles", help="list browser profiles")
    profiles_parser.set_defaults(func=_cmd_profiles)

    cookies_parser = youtube_sub.add_parser("cookies", help="export/check YouTube cookies")
    cookies_parser.add_argument("--profile", required=True)
    cookies_parser.add_argument("--out", type=Path)
    cookies_parser.set_defaults(func=_cmd_cookies)

    download_parser = youtube_sub.add_parser("download", help="download registered channels")
    download_parser.add_argument("--channel", help="one channel slug")
    download_parser.add_argument("--group", help="all channels in a group")
    download_parser.add_argument("--language", help="all channels with an ISO-639-3 language")
    download_parser.add_argument("--profile", help="override configured browser profile")
    download_parser.add_argument("--limit", type=int, help="playlist cap per selected channel")
    download_parser.add_argument("--dry-run", action="store_true")
    download_parser.add_argument("--no-factory", action="store_true")
    download_parser.set_defaults(func=_cmd_download)

    list_parser.set_defaults(func=_cmd_list)

    for step in PIPELINE_STEPS:
        step_parser = subparsers.add_parser(step, help=f"run the {step} pipeline step")
        step_parser.add_argument("rest", nargs=argparse.REMAINDER,
                                 help="arguments forwarded to the step")

    args = parser.parse_args(argv)
    if args.command in PIPELINE_STEPS:
        return _run_step(args.command, args.rest)
    registry = load_registry(args.config) if args.config else load_registry()
    return args.func(registry, args)


def _cmd_list(registry: YoutubeRegistry, args: argparse.Namespace) -> int:
    channels = registry.selected(group=args.group, language=args.language)
    for channel in channels:
        print(
            f"{channel.slug:28s} {channel.group:7s} {channel.language:3s} "
            f"{channel.profile:15s} {channel.url}"
        )
    print(f"{len(channels)} channel(s)")
    return 0


def _cmd_profiles(registry: YoutubeRegistry, _args: argparse.Namespace) -> int:
    for profile in registry.profiles.values():
        exists = "ok" if profile.path.exists() else "missing"
        print(f"{profile.name:16s} {exists:7s} {profile.browser_spec}")
    return 0


def _cmd_cookies(registry: YoutubeRegistry, args: argparse.Namespace) -> int:
    profile = registry.profiles[args.profile]
    out, count = refresh_cookies(profile, args.out)
    print(f"{count} youtube.com cookie(s) -> {out}")
    if count == 0:
        return 2
    return 0


def _cmd_download(registry: YoutubeRegistry, args: argparse.Namespace) -> int:
    channels = registry.selected(slug=args.channel, group=args.group, language=args.language)
    if not channels:
        print("no channels selected")
        return 1
    results = download_channels(
        registry,
        channels,
        profile_override=args.profile,
        limit=args.limit,
        dry_run=args.dry_run,
        run_factory=not args.no_factory,
    )
    for result in results:
        print(f"{result.channel.slug:28s} {result.media_count:5d} file(s) -> {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
