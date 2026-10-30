"""Updater and CycleRuns adapters for the frontend: git and the GitHub CLI, run in the knowledge base's clone."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from instaautomation.ports import CycleRun

CYCLE_WORKFLOW = "cycle.yml"


class GitUpdater:
    def __init__(self, repo_dir: Path) -> None:
        self._repo_dir = repo_dir

    def update(self) -> str | None:
        # --ff-only never merges or rewrites anything: local edits or a diverged branch just make it refuse.
        try:
            result = subprocess.run(
                ["git", "-C", str(self._repo_dir), "pull", "--ff-only"],
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
                # Fail instead of waiting for a password nobody will type.
                env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError:
            return "git is not installed"
        except subprocess.TimeoutExpired:
            return "git pull timed out (offline?)"
        if result.returncode != 0:
            lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
            return next((line for line in lines if line.startswith(("fatal:", "error:"))), lines[-1] if lines else "git pull failed")
        return None


class GhCycleRuns:
    def __init__(self, repo_dir: Path, limit: int = 10) -> None:
        self._repo_dir = repo_dir
        self._limit = limit

    def latest(self) -> list[CycleRun] | None:
        try:
            result = subprocess.run(
                ["gh", "run", "list", "--workflow", CYCLE_WORKFLOW, "--limit", str(self._limit), "--json", "createdAt,status,conclusion,url"],
                cwd=self._repo_dir,
                capture_output=True,
                text=True,
                timeout=20,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return None
            return [
                CycleRun(
                    started_at=datetime.fromisoformat(run["createdAt"]),
                    outcome=run["conclusion"] or run["status"],
                    url=run["url"],
                )
                for run in json.loads(result.stdout)
            ]
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            # gh missing, logged out, offline or changed its output: the status page goes without runs.
            return None
