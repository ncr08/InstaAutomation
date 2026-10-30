"""Production entry point: one cycle with the real adapters, as the scheduled workflow runs it.

Usage: python -m instaautomation [KB_DIR]   (default: kb)
Secrets are read from the environment, under the names listed in .env.example.
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from instaautomation.deepseek import DeepSeekSummarizer
from instaautomation.groq import GroqTranscriber
from instaautomation.hikerapi import HikerReelSource
from instaautomation.ocr import OcrScreenReader
from instaautomation.pipeline import run_cycle
from instaautomation.ports import Ports
from instaautomation.telegram import TelegramInbox


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    # httpx logs every request URL at INFO, and Telegram's include the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    kb_dir = Path(argv[0]) if argv else Path("kb")
    ports = Ports(
        inbox=TelegramInbox.from_env(),
        reel_source=HikerReelSource.from_env(),
        transcriber=GroqTranscriber.from_env(),
        screen_reader=OcrScreenReader(),
        summarizer=DeepSeekSummarizer.from_env(),
        clock=SystemClock(),
    )
    run_cycle(ports, kb_dir, owner_id=int(os.environ["TELEGRAM_OWNER_ID"]))


if __name__ == "__main__":
    main(sys.argv[1:])
