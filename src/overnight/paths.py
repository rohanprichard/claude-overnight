"""Filesystem layout. Everything lives under ~/.overnight (override with OVERNIGHT_HOME)."""

import os
from pathlib import Path


def base_dir() -> Path:
    return Path(os.environ.get("OVERNIGHT_HOME", Path.home() / ".overnight"))


def config_path() -> Path:
    return base_dir() / "config.toml"


def queue_dir() -> Path:
    return base_dir() / "queue"


def results_dir() -> Path:
    return base_dir() / "results"


def scratch_dir() -> Path:
    return base_dir() / "scratch"


def logs_dir() -> Path:
    return base_dir() / "logs"


def lock_path() -> Path:
    return base_dir() / "runner.lock"


def ensure_dirs() -> None:
    for d in (base_dir(), queue_dir(), results_dir(), scratch_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)
