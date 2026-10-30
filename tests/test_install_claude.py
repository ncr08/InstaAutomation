import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IMPORT_LINE = f"@{ROOT}/kb/claude-block.md"


def install(config_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "install_claude.py")],
        env={**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)},
        capture_output=True,
        text=True,
    )


def session_start_commands(config_dir: Path) -> list[str]:
    settings = json.loads((config_dir / "settings.json").read_text())
    return [hook["command"] for group in settings["hooks"]["SessionStart"] for hook in group["hooks"]]


def test_fresh_install_imports_the_block_links_the_skill_and_pulls_on_session_start(tmp_path: Path) -> None:
    result = install(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "CLAUDE.md").read_text() == IMPORT_LINE + "\n"
    assert (tmp_path / "skills" / "ai-kb").resolve() == ROOT / "skills" / "ai-kb"
    [command] = session_start_commands(tmp_path)
    assert f"git -C {ROOT} " in command and "pull --ff-only" in command


def test_existing_instructions_and_settings_are_kept_and_a_rerun_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# My rules\n\nBe brief.")
    other_hook = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}
    (tmp_path / "settings.json").write_text(
        json.dumps({"model": "opus", "hooks": {"SessionStart": [other_hook], "Stop": []}}, indent=2)
    )

    assert install(tmp_path).returncode == 0
    first = {name: (tmp_path / name).read_text() for name in ("CLAUDE.md", "settings.json")}
    second_run = install(tmp_path)

    assert second_run.returncode == 0, second_run.stderr
    assert {name: (tmp_path / name).read_text() for name in first} == first
    assert first["CLAUDE.md"] == f"# My rules\n\nBe brief.\n{IMPORT_LINE}\n"
    settings = json.loads(first["settings.json"])
    assert settings["model"] == "opus"
    assert settings["hooks"]["Stop"] == []
    assert settings["hooks"]["SessionStart"][0] == other_hook
    assert len(session_start_commands(tmp_path)) == 2


@pytest.mark.parametrize(
    "unreadable",
    ['{"model": "opus",', '["opus"]', '{"hooks": {"SessionStart": [{"hooks": ["echo hi"]}]}}'],
)
def test_unreadable_settings_abort_before_anything_is_written(tmp_path: Path, unreadable: str) -> None:
    (tmp_path / "settings.json").write_text(unreadable)

    result = install(tmp_path)

    assert result.returncode != 0
    assert "settings.json" in result.stderr and "Traceback" not in result.stderr
    assert (tmp_path / "settings.json").read_text() == unreadable
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "skills").exists()


def test_an_existing_skill_that_is_not_ours_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "skills" / "ai-kb").mkdir(parents=True)

    result = install(tmp_path)

    assert result.returncode != 0
    assert "ai-kb" in result.stderr
    assert (tmp_path / "skills" / "ai-kb").is_dir() and not (tmp_path / "skills" / "ai-kb").is_symlink()
    assert not (tmp_path / "CLAUDE.md").exists()
