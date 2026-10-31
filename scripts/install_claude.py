#!/usr/bin/env python3
"""One-time local install of the knowledge base into Claude Code and macOS. Safe to re-run.

- adds one import line for the Claude block to the global Claude instructions (nothing else there is touched),
- symlinks the /ai-kb skill into the Claude skills directory,
- adds a SessionStart hook that quietly pulls this clone, giving up fast when offline,
- installs a launchd job that pulls this clone and rebuilds the static site in site/ every hour,
  at login and after the Mac wakes; the log goes to ~/Library/Logs.

Uses only the standard library so the system python3 can run it: python3 scripts/install_claude.py
python3 scripts/install_claude.py --uninstall removes the launchd job and leaves everything else alone.
"""

import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
# Overridable so the tests never touch the real launchd.
LAUNCH_AGENTS_DIR = Path(os.environ.get("LAUNCH_AGENTS_DIR") or Path.home() / "Library" / "LaunchAgents")
LOG_DIR = Path(os.environ.get("LAUNCH_LOG_DIR") or Path.home() / "Library" / "Logs")
LAUNCHCTL = os.environ.get("LAUNCHCTL", "launchctl")
SITE_JOB = "com.instaautomation.site"


def main() -> None:
    if sys.argv[1:] == ["--uninstall"]:
        uninstall_site_job()
        return
    if sys.argv[1:]:
        sys.exit("Usage: python3 scripts/install_claude.py [--uninstall]")
    # Everything is read and checked before the first write, so a refusal leaves the config untouched.
    instructions = CONFIG_DIR / "CLAUDE.md"
    import_line = f"@{REPO / 'kb' / 'claude-block.md'}"
    existing_instructions = instructions.read_text() if instructions.exists() else ""

    skill_link = CONFIG_DIR / "skills" / "ai-kb"
    skill_target = REPO / "skills" / "ai-kb"
    if skill_link.is_symlink() and skill_link.resolve() != skill_target.resolve():
        _refuse(f"{skill_link} links to {skill_link.resolve()}, not {skill_target}; remove it and re-run")
    if skill_link.exists() and not skill_link.is_symlink():
        _refuse(f"{skill_link} already exists and is not a link to this repo; move it away and re-run")

    settings_file = CONFIG_DIR / "settings.json"
    settings = _read_settings(settings_file)
    session_start = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    command = _pull_command()
    # Matched on the exact command, so after moving the clone the old hook stays: remove it by hand.
    hook_installed = any(hook.get("command") == command for group in session_start for hook in group["hooks"])
    uv = shutil.which("uv")
    if uv is None:
        _refuse("uv is not on PATH, and the site job runs the export with it; install uv and re-run")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if import_line not in existing_instructions.splitlines():
        separator = "\n" if existing_instructions and not existing_instructions.endswith("\n") else ""
        instructions.write_text(f"{existing_instructions}{separator}{import_line}\n")
    if not skill_link.is_symlink():
        skill_link.parent.mkdir(parents=True, exist_ok=True)
        skill_link.symlink_to(skill_target)
    if not hook_installed:
        # The hook's own timeout bounds the pull, as macOS has no timeout(1).
        session_start.append({"matcher": "startup", "hooks": [{"type": "command", "command": command, "timeout": 15}]})
        _write_atomically(settings_file, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    plist = install_site_job(uv)
    print(f"Installed: {import_line} in {instructions}, {skill_link} -> {skill_target}, SessionStart pull hook, {plist}.")
    print(f"Bookmark {(REPO / 'site' / 'index.html').as_uri()}")


def install_site_job(uv: str) -> Path:
    """Writes the launchd job and (re)loads it when it changed or isn't loaded; otherwise leaves it be."""
    plist = LAUNCH_AGENTS_DIR / f"{SITE_JOB}.plist"
    log = LOG_DIR / "instaautomation-site.log"
    job = {
        "Label": SITE_JOB,
        "ProgramArguments": [uv, "run", "--project", str(REPO), "python", "-m", "instaautomation", "export"],
        "WorkingDirectory": str(REPO),
        # launchd's own PATH lacks Homebrew, where git and gh usually live.
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "RunAtLoad": True,
        # On the hour; an hour slept through is caught up once on wake, which StartInterval wouldn't do.
        "StartCalendarInterval": {"Minute": 0},
        "ProcessType": "Background",
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    content = plistlib.dumps(job)
    changed = not plist.exists() or plist.read_bytes() != content
    if changed:
        plist.parent.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(plist, content)
    if changed or not _loaded():
        _launchctl("bootout", _target(), check=False)
        _launchctl("bootstrap", _domain(), str(plist))
    return plist


def uninstall_site_job() -> None:
    plist = LAUNCH_AGENTS_DIR / f"{SITE_JOB}.plist"
    _launchctl("bootout", _target(), check=False)
    plist.unlink(missing_ok=True)
    print(f"Removed the site job ({plist}). The rest of the install is unchanged.")


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _target() -> str:
    return f"{_domain()}/{SITE_JOB}"


def _loaded() -> bool:
    return _launchctl("print", _target(), check=False).returncode == 0


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([LAUNCHCTL, *args], capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        sys.exit(f"launchctl {args[0]} failed: {result.stderr.strip() or result.returncode}")
    return result


def _read_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        _refuse(f"{path} is not valid JSON ({error}); fix it and re-run")
    if not isinstance(settings, dict):
        _refuse(f"{path} is not a JSON object; fix it and re-run")
    hooks = settings.get("hooks", {})
    session_start = hooks.get("SessionStart", []) if isinstance(hooks, dict) else None
    if not isinstance(session_start, list) or not all(
        isinstance(group, dict)
        and isinstance(group.get("hooks"), list)
        and all(isinstance(hook, dict) for hook in group["hooks"])
        for group in session_start
    ):
        _refuse(f"{path} has hooks in a shape this installer doesn't recognise; add the hook by hand")
    return settings


def _write_atomically(path: Path, content: str | bytes) -> None:
    # A crash mid-write must never leave the owner's settings truncated.
    temporary = path.with_name(f".{path.name}.tmp")
    if isinstance(content, bytes):
        temporary.write_bytes(content)
    else:
        temporary.write_text(content)
    os.replace(temporary, path)


def _refuse(reason: str) -> NoReturn:
    sys.exit(f"Nothing installed: {reason}.")


def _pull_command() -> str:
    # Its output would land in Claude's context, hence silent; it must never fail or prompt, hence || true and no TTY.
    return (
        "GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=5' "
        f"git -C {shlex.quote(str(REPO))} -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 "
        "pull --ff-only --quiet >/dev/null 2>&1 || true"
    )


if __name__ == "__main__":
    main()
