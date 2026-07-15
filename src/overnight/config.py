"""Config: a small TOML file with a night window and utilization thresholds."""

import tomllib
from dataclasses import dataclass, field
from datetime import time

from . import paths

DEFAULT_CONFIG_TOML = """\
# claude-overnight configuration

[window]
# Jobs only run between these local times. A window may cross midnight
# (e.g. start = "23:00", end = "06:00").
start = "01:00"
end = "07:00"

[limits]
# Don't start a batch if the 5-hour window is already above this % used.
start_max_utilization = 20
# Stop the batch once 5-hour utilization crosses this %, so you wake up
# with quota left.
stop_utilization = 60
# Never run if the weekly limit is above this % used.
weekly_max_utilization = 80

[run]
model = "sonnet"
job_timeout_minutes = 15
max_attempts = 2
# Extra flags passed through to `claude -p`.
extra_args = []
"""


@dataclass
class Config:
    window_start: time = time(1, 0)
    window_end: time = time(7, 0)
    start_max_utilization: float = 20.0
    stop_utilization: float = 60.0
    weekly_max_utilization: float = 80.0
    model: str = "sonnet"
    job_timeout_minutes: int = 15
    max_attempts: int = 2
    extra_args: list[str] = field(default_factory=list)


def _parse_time(value: str) -> time:
    hh, mm = value.strip().split(":")
    return time(int(hh), int(mm))


def load() -> Config:
    """Load config, writing the default file on first run."""
    path = paths.config_path()
    if not path.exists():
        paths.ensure_dirs()
        path.write_text(DEFAULT_CONFIG_TOML)
    data = tomllib.loads(path.read_text())
    cfg = Config()
    window = data.get("window", {})
    if "start" in window:
        cfg.window_start = _parse_time(window["start"])
    if "end" in window:
        cfg.window_end = _parse_time(window["end"])
    limits = data.get("limits", {})
    cfg.start_max_utilization = float(limits.get("start_max_utilization", cfg.start_max_utilization))
    cfg.stop_utilization = float(limits.get("stop_utilization", cfg.stop_utilization))
    cfg.weekly_max_utilization = float(limits.get("weekly_max_utilization", cfg.weekly_max_utilization))
    run = data.get("run", {})
    cfg.model = run.get("model", cfg.model)
    cfg.job_timeout_minutes = int(run.get("job_timeout_minutes", cfg.job_timeout_minutes))
    cfg.max_attempts = int(run.get("max_attempts", cfg.max_attempts))
    cfg.extra_args = list(run.get("extra_args", []))
    return cfg


def in_window(cfg: Config, now: time) -> bool:
    """True if `now` falls inside the configured night window.

    Handles windows that cross midnight: start=23:00 end=06:00 matches 23:30
    and 05:59 but not 12:00.
    """
    start, end = cfg.window_start, cfg.window_end
    if start <= end:
        return start <= now < end
    return now >= start or now < end
