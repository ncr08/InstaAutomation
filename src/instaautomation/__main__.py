"""Entry point.

    python -m instaautomation [KB_DIR]              one cycle with the real adapters, as the scheduled workflow runs it
    python -m instaautomation covers [KB_DIR]       one-off: fetch a cover for every entry that has none
    python -m instaautomation export [KB_DIR] [--out SITE_DIR] [--no-pull]
                                                    pull, then build the static site (default: site/index.html)

KB_DIR defaults to kb. Secrets are read from the environment, under the names listed in .env.example;
the frontend needs none.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from instaautomation.covers import FfmpegCoverMaker
from instaautomation.deepseek import DeepSeekSummarizer
from instaautomation.groq import GroqTranscriber
from instaautomation.hikerapi import HikerReelSource
from instaautomation.ocr import OcrScreenReader
from instaautomation.pipeline import backfill_covers, run_cycle
from instaautomation.ports import Ports
from instaautomation.repo import GhCycleRuns, GitUpdater
from instaautomation.telegram import TelegramInbox
from instaautomation.ui import build_site


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    # httpx logs every request URL at INFO, and Telegram's include the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Subcommands only by name, so the workflow's `python -m instaautomation kb` stays a cycle on KB_DIR kb.
    if argv[:1] == ["covers"]:
        covers(argv[1:])
    elif argv[:1] == ["export"]:
        export(argv[1:])
    else:
        cycle(argv)


def cycle(argv: list[str]) -> None:
    kb_dir = Path(argv[0]) if argv else Path("kb")
    ports = Ports(
        inbox=TelegramInbox.from_env(),
        reel_source=HikerReelSource.from_env(),
        transcriber=GroqTranscriber.from_env(),
        screen_reader=OcrScreenReader(),
        summarizer=DeepSeekSummarizer.from_env(),
        cover_maker=FfmpegCoverMaker(),
        clock=SystemClock(),
    )
    run_cycle(ports, kb_dir, owner_id=int(os.environ["TELEGRAM_OWNER_ID"]))


def covers(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m instaautomation covers", description="Fetch a cover for every entry that has none.")
    parser.add_argument("kb_dir", nargs="?", type=Path, default=Path("kb"))
    args = parser.parse_args(argv)
    report = backfill_covers(HikerReelSource.from_env(), FfmpegCoverMaker(), args.kb_dir)
    for shortcode in report.added:
        print(f"added   {shortcode}")
    for shortcode, reason in report.failed.items():
        print(f"failed  {shortcode}: {reason}")
    print(f"{len(report.added)} covers added, {len(report.failed)} failed")


def export(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m instaautomation export", description="Pull the knowledge base, then build the static site.")
    parser.add_argument("kb_dir", nargs="?", type=Path, default=Path("kb"))
    parser.add_argument("--out", type=Path, default=Path("site"))
    parser.add_argument("--no-pull", action="store_true", help="build from the files as they are, e.g. the demo knowledge base")
    args = parser.parse_args(argv)
    failure = None if args.no_pull else GitUpdater(args.kb_dir).update()
    if failure:
        print(f"Could not update the knowledge base, building from local files: {failure}")
    # launchd starts the job without the owner's shell environment, so the clone's .env is the usual source.
    ai_key = os.environ.get("DEEPSEEK_API_KEY") or _dotenv(args.kb_dir.resolve().parent / ".env").get("DEEPSEEK_API_KEY")
    if not ai_key:
        print("No DEEPSEEK_API_KEY in the environment or .env: building without AI search.")
    build_site(args.kb_dir, args.out, update_failure=failure, cycle_runs=GhCycleRuns(args.kb_dir), clock=SystemClock(), ai_key=ai_key)
    print(f"Wrote {(args.out / 'index.html').resolve().as_uri()}")


def _dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; blank lines, comments and anything else are skipped."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("'\"")
    return values


if __name__ == "__main__":
    main(sys.argv[1:])
