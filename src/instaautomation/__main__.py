"""Entry point.

    python -m instaautomation [KB_DIR]              one cycle with the real adapters, as the scheduled workflow runs it
    python -m instaautomation covers [KB_DIR]       one-off: fetch a cover for every entry that has none
    python -m instaautomation ui [KB_DIR] [--port]  the local, read-only frontend in the browser

KB_DIR defaults to kb. Secrets are read from the environment, under the names listed in .env.example;
the frontend needs none.
"""

import argparse
import logging
import os
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

from instaautomation.covers import FfmpegCoverMaker
from instaautomation.deepseek import DeepSeekSummarizer
from instaautomation.groq import GroqTranscriber
from instaautomation.hikerapi import HikerReelSource
from instaautomation.ocr import OcrScreenReader
from instaautomation.pipeline import backfill_covers, run_cycle
from instaautomation.ports import Ports
from instaautomation.repo import GhCycleRuns, GitUpdater
from instaautomation.telegram import TelegramInbox
from instaautomation.ui import make_app


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
    elif argv[:1] == ["ui"]:
        ui(argv[1:])
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


def ui(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m instaautomation ui", description="Browse the knowledge base and pipeline status.")
    parser.add_argument("kb_dir", nargs="?", type=Path, default=Path("kb"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    print("Updating the knowledge base (git pull --ff-only)…")
    app = make_app(args.kb_dir, GitUpdater(args.kb_dir), GhCycleRuns(args.kb_dir))
    # Localhost only: the knowledge base is private.
    with make_server("127.0.0.1", args.port, app, handler_class=_QuietHandler) as server:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Serving {args.kb_dir} at {url} (Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
