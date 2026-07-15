"""Install/uninstall the launchd agent and the /queue slash command."""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

LAUNCHD_LABEL = "com.claude-overnight.runner"
TICK_SECONDS = 30 * 60

SLASH_COMMAND = """\
---
description: Queue a question for claude-overnight to research when your limits reset
allowed-tools: Bash(overnight add:*)
---

Run `overnight add "$ARGUMENTS"` and confirm to the user that the question
was queued, mentioning it will run in the next overnight window.
"""


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _runner_command() -> list[str]:
    exe = shutil.which("overnight")
    if exe:
        return [exe, "run"]
    return [sys.executable, "-m", "overnight.cli", "run"]


def install_launchd() -> Path:
    paths.ensure_dirs()
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": _runner_command(),
        "StartInterval": TICK_SECONDS,
        "RunAtLoad": False,
        "StandardOutPath": str(paths.logs_dir() / "runner.log"),
        "StandardErrorPath": str(paths.logs_dir() / "runner.err.log"),
    }
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(path)], capture_output=True)
    return path


def uninstall_launchd() -> bool:
    path = _plist_path()
    if not path.exists():
        return False
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    path.unlink()
    return True


def install_slash_command() -> Path:
    path = Path.home() / ".claude" / "commands" / "queue.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SLASH_COMMAND)
    return path


def uninstall_slash_command() -> bool:
    path = Path.home() / ".claude" / "commands" / "queue.md"
    if path.exists():
        path.unlink()
        return True
    return False
