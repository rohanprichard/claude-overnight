"""Desktop notification (osascript on macOS, notify-send on Linux).
Best-effort: failures are ignored."""

import subprocess
import sys


def send(title: str, message: str) -> None:
    if sys.platform == "darwin":
        cmd = ["osascript", "-e",
               f'display notification "{_esc(message)}" with title "{_esc(title)}"']
    else:
        cmd = ["notify-send", title, message]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
