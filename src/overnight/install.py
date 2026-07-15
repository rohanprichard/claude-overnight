"""Install/uninstall the scheduler (launchd on macOS, systemd user timer on
Linux) and the /queue slash command."""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

LAUNCHD_LABEL = "com.claude-overnight.runner"
SYSTEMD_UNIT = "claude-overnight"
TICK_MINUTES = 30

SLASH_COMMAND = """\
---
description: Queue a question for claude-overnight to research when your limits reset
allowed-tools: Bash(overnight add:*)
---

Run `overnight add "$ARGUMENTS"` and confirm to the user that the question
was queued, mentioning it will run in the next overnight window.
"""


def _runner_command() -> list[str]:
    exe = shutil.which("overnight")
    if exe:
        return [exe, "run"]
    return [sys.executable, "-m", "overnight.cli", "run"]


def install_scheduler() -> Path:
    if sys.platform == "darwin":
        return install_launchd()
    return install_systemd()


def uninstall_scheduler() -> bool:
    if sys.platform == "darwin":
        return uninstall_launchd()
    return uninstall_systemd()


# --- macOS ---

def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install_launchd() -> Path:
    paths.ensure_dirs()
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": _runner_command(),
        "StartInterval": TICK_MINUTES * 60,
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


# --- Linux ---

def _systemd_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def systemd_units() -> tuple[str, str]:
    exec_line = " ".join(_runner_command())
    service = (
        "[Unit]\n"
        "Description=claude-overnight queue runner\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={exec_line}\n"
        f"StandardOutput=append:{paths.logs_dir() / 'runner.log'}\n"
        f"StandardError=append:{paths.logs_dir() / 'runner.err.log'}\n"
    )
    timer = (
        "[Unit]\n"
        "Description=Run claude-overnight every 30 minutes\n\n"
        "[Timer]\n"
        f"OnCalendar=*:0/{TICK_MINUTES}\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def install_systemd() -> Path:
    paths.ensure_dirs()
    unit_dir = _systemd_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service, timer = systemd_units()
    (unit_dir / f"{SYSTEMD_UNIT}.service").write_text(service)
    timer_path = unit_dir / f"{SYSTEMD_UNIT}.timer"
    timer_path.write_text(timer)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"],
                   capture_output=True)
    return timer_path


def uninstall_systemd() -> bool:
    unit_dir = _systemd_dir()
    timer_path = unit_dir / f"{SYSTEMD_UNIT}.timer"
    if not timer_path.exists():
        return False
    subprocess.run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"],
                   capture_output=True)
    timer_path.unlink()
    (unit_dir / f"{SYSTEMD_UNIT}.service").unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    return True


# --- slash command ---

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
