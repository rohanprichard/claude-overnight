"""macOS notification via osascript. Best-effort: failures are ignored."""

import subprocess


def send(title: str, message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{_esc(message)}" with title "{_esc(title)}"'],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
