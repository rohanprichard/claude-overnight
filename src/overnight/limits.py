"""Read Claude Code usage limits.

There is no official API. Two community-discovered sources exist:

1. `GET https://api.anthropic.com/api/oauth/usage` with the OAuth access
   token Claude Code already stores locally. Returns 5-hour and 7-day
   utilization percentages and reset timestamps.
2. Claude Code >= 2.1.80 passes the same data to statusline scripts on
   stdin (not usable from a background runner).

We use (1) and degrade gracefully: if the token is missing/expired or the
endpoint changes, `fetch_usage()` returns None and the runner proceeds
optimistically, detecting limit errors from `claude -p` output instead.
"""

import json
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
KEYCHAIN_SERVICE = "Claude Code-credentials"


@dataclass
class Usage:
    five_hour_pct: float | None = None
    five_hour_resets_at: str | None = None
    seven_day_pct: float | None = None
    seven_day_resets_at: str | None = None


def _token_from_credentials_file() -> str | None:
    path = Path.home() / ".claude" / ".credentials.json"
    try:
        data = json.loads(path.read_text())
        return data.get("claudeAiOauth", {}).get("accessToken")
    except (OSError, json.JSONDecodeError):
        return None


def _token_from_keychain() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout.strip()).get("claudeAiOauth", {}).get("accessToken")
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def get_access_token() -> str | None:
    return _token_from_credentials_file() or _token_from_keychain()


def parse_usage(payload: dict) -> Usage:
    """Parse the oauth/usage response defensively — it's undocumented.

    Two shapes observed in the wild:
    - modern: a `limits` list with entries like
      {"kind": "session"|"weekly_scoped", "percent": 27.5, "resets_at": ...}
    - legacy: top-level `five_hour`/`seven_day` dicts with `utilization`.
    Weekly can appear as several scoped entries (per model); we keep the
    highest active one, since any exhausted scope blocks that model.
    """
    usage = Usage()
    for entry in payload.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", ""))
        pct = _pct(entry.get("percent"))
        if pct is None:
            continue
        if kind == "session":
            usage.five_hour_pct = pct
            usage.five_hour_resets_at = entry.get("resets_at")
        elif kind.startswith("weekly"):
            if usage.seven_day_pct is None or pct > usage.seven_day_pct:
                usage.seven_day_pct = pct
                usage.seven_day_resets_at = entry.get("resets_at")

    five = payload.get("five_hour") or {}
    seven = payload.get("seven_day") or {}
    if usage.five_hour_pct is None and isinstance(five, dict):
        usage.five_hour_pct = _pct(five.get("utilization"))
        usage.five_hour_resets_at = five.get("resets_at")
    if usage.seven_day_pct is None and isinstance(seven, dict):
        usage.seven_day_pct = _pct(seven.get("utilization"))
        usage.seven_day_resets_at = seven.get("resets_at")
    return usage


def _pct(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_usage(timeout: int = 15) -> Usage | None:
    """Fetch current utilization. Returns None on any failure — callers
    must treat that as "unknown", not "zero"."""
    token = get_access_token()
    if not token:
        return None
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA_HEADER,
            "User-Agent": "claude-overnight",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_usage(json.loads(resp.read().decode()))
    except Exception:
        return None
