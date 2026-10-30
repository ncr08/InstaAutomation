"""Durable pipeline state, committed with the knowledge base so nothing is lost between cycles."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from instaautomation.ports import MessageRef

STATE_FILE = "state.json"


@dataclass
class QueueItem:
    shortcode: str
    url: str
    ref: MessageRef
    attempts: int = 0
    last_error: str | None = None


@dataclass
class State:
    offset: int = 0
    pending: list[QueueItem] = field(default_factory=list)
    failed: list[QueueItem] = field(default_factory=list)
    processed: set[str] = field(default_factory=set)


def load_state(kb_dir: Path) -> State:
    path = kb_dir / STATE_FILE
    if not path.exists():
        return State()
    raw = json.loads(path.read_text())
    return State(
        offset=raw["offset"],
        pending=[_item(entry) for entry in raw["pending"]],
        failed=[_item(entry) for entry in raw["failed"]],
        processed=set(raw["processed"]),
    )


def save_state(kb_dir: Path, state: State) -> None:
    """Write atomically, so a crash mid-write never leaves a truncated state file."""
    kb_dir.mkdir(parents=True, exist_ok=True)
    path = kb_dir / STATE_FILE
    tmp = path.with_suffix(".tmp")
    raw = asdict(state) | {"processed": sorted(state.processed)}
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _item(raw: dict[str, Any]) -> QueueItem:
    return QueueItem(
        shortcode=raw["shortcode"],
        url=raw["url"],
        ref=MessageRef(**raw["ref"]),
        attempts=raw["attempts"],
        last_error=raw["last_error"],
    )
