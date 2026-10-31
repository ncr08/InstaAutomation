import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IMPORT_LINE = f"@{ROOT}/kb/claude-block.md"


SITE_JOB = "com.instaautomation.site"

# Stands in for launchctl: records each call and remembers whether the job is loaded.
FAKE_LAUNCHCTL = """#!/bin/sh
d=$(dirname "$0")
echo "$*" >> "$d/calls"
case "$1" in
  print) [ -f "$d/loaded" ] ;;
  bootstrap) touch "$d/loaded" ;;
  bootout) [ -f "$d/loaded" ] && rm "$d/loaded" || exit 3 ;;
esac
"""


def install(config_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    launchd = config_dir / "launchd"
    launchd.mkdir(exist_ok=True)
    launchctl = launchd / "launchctl"
    if not launchctl.exists():
        launchctl.write_text(FAKE_LAUNCHCTL)
        launchctl.chmod(0o755)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "install_claude.py"), *args],
        env={
            **os.environ,
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "LAUNCH_AGENTS_DIR": str(launchd / "LaunchAgents"),
            "LAUNCH_LOG_DIR": str(launchd / "Logs"),
            "LAUNCHCTL": str(launchctl),
        },
        capture_output=True,
        text=True,
    )


def site_job_plist(config_dir: Path) -> Path:
    return config_dir / "launchd" / "LaunchAgents" / f"{SITE_JOB}.plist"


def launchctl_calls(config_dir: Path) -> list[str]:
    calls = config_dir / "launchd" / "calls"
    return [line.split()[0] for line in calls.read_text().splitlines()] if calls.exists() else []


def job_loaded(config_dir: Path) -> bool:
    return (config_dir / "launchd" / "loaded").exists()


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


def test_the_site_job_rebuilds_the_site_from_this_clone_hourly_and_at_login(tmp_path: Path) -> None:
    result = install(tmp_path)

    assert result.returncode == 0, result.stderr
    job = plistlib.loads(site_job_plist(tmp_path).read_bytes())
    assert job["Label"] == SITE_JOB
    assert job["ProgramArguments"][1:] == ["run", "--project", str(ROOT), "python", "-m", "instaautomation", "export"]
    assert Path(job["ProgramArguments"][0]).name == "uv"
    assert job["WorkingDirectory"] == str(ROOT)
    assert job["RunAtLoad"] is True
    assert job["StartCalendarInterval"] == {"Minute": 0}
    assert job["StandardOutPath"] == job["StandardErrorPath"] == str(tmp_path / "launchd" / "Logs" / "instaautomation-site.log")
    assert "/" in job["EnvironmentVariables"]["PATH"]
    assert job_loaded(tmp_path)
    assert (ROOT / "site" / "index.html").as_uri() in result.stdout


def test_rerunning_the_installer_leaves_a_loaded_site_job_alone(tmp_path: Path) -> None:
    install(tmp_path)
    plist = site_job_plist(tmp_path).read_bytes()
    calls_after_first = launchctl_calls(tmp_path)

    assert install(tmp_path).returncode == 0

    assert site_job_plist(tmp_path).read_bytes() == plist
    assert launchctl_calls(tmp_path)[len(calls_after_first):] == ["print"]


def test_rerunning_the_installer_reloads_a_site_job_that_was_unloaded(tmp_path: Path) -> None:
    install(tmp_path)
    (tmp_path / "launchd" / "loaded").unlink()

    assert install(tmp_path).returncode == 0

    assert job_loaded(tmp_path)


def test_uninstall_removes_only_the_site_job(tmp_path: Path) -> None:
    install(tmp_path)
    before = {name: (tmp_path / name).read_text() for name in ("CLAUDE.md", "settings.json")}

    result = install(tmp_path, "--uninstall")

    assert result.returncode == 0, result.stderr
    assert not site_job_plist(tmp_path).exists()
    assert not job_loaded(tmp_path)
    assert {name: (tmp_path / name).read_text() for name in before} == before
    assert (tmp_path / "skills" / "ai-kb").is_symlink()


def test_a_refused_install_does_not_touch_the_site_job(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text('{"model": "opus",')

    assert install(tmp_path).returncode != 0

    assert not site_job_plist(tmp_path).exists()
    assert launchctl_calls(tmp_path) == []
