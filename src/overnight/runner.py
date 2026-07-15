"""The batch runner: decides whether to run, executes jobs via `claude -p`,
writes markdown reports and a rolling index."""

import json
import os
import shutil
import subprocess
import time as time_mod
from dataclasses import dataclass
from datetime import datetime

from . import limits, notify, paths, store
from .config import Config, in_window

PROMPT_TEMPLATE = """\
You are running unattended overnight; nobody can answer questions, so make \
reasonable assumptions and state them. Research the question below using web \
search where useful, and produce a complete, self-contained markdown report. \
Start with a short executive summary, then the details, then a Sources \
section with links.

Question:
{prompt}
"""

LIMIT_ERROR_MARKERS = ("usage limit", "rate limit", "limit reached", "out of quota")
LOCK_STALE_SECONDS = 2 * 60 * 60


@dataclass
class Decision:
    run: bool
    reason: str


def should_start(cfg: Config, usage: limits.Usage | None, now: datetime, force: bool = False) -> Decision:
    if force:
        return Decision(True, "forced")
    if not in_window(cfg, now.time()):
        return Decision(False, f"outside window {cfg.window_start:%H:%M}-{cfg.window_end:%H:%M}")
    if usage is None:
        return Decision(True, "usage unknown; proceeding optimistically")
    if usage.seven_day_pct is not None and usage.seven_day_pct > cfg.weekly_max_utilization:
        return Decision(False, f"weekly limit at {usage.seven_day_pct:.0f}% (cap {cfg.weekly_max_utilization:.0f}%)")
    if usage.five_hour_pct is not None and usage.five_hour_pct > cfg.start_max_utilization:
        return Decision(False, f"5h window at {usage.five_hour_pct:.0f}% (start cap {cfg.start_max_utilization:.0f}%)")
    return Decision(True, "limits look clear")


def should_continue(cfg: Config, usage: limits.Usage | None, now: datetime, force: bool = False) -> Decision:
    if force:
        return Decision(True, "forced")
    if not in_window(cfg, now.time()):
        return Decision(False, "window ended")
    if usage is None:
        return Decision(True, "usage unknown; continuing")
    if usage.five_hour_pct is not None and usage.five_hour_pct >= cfg.stop_utilization:
        return Decision(False, f"5h window reached {usage.five_hour_pct:.0f}% (stop cap {cfg.stop_utilization:.0f}%)")
    if usage.seven_day_pct is not None and usage.seven_day_pct > cfg.weekly_max_utilization:
        return Decision(False, "weekly cap reached")
    return Decision(True, "ok")


def _acquire_lock() -> bool:
    paths.ensure_dirs()
    lock = paths.lock_path()
    if lock.exists():
        age = time_mod.time() - lock.stat().st_mtime
        if age < LOCK_STALE_SECONDS:
            return False
        lock.unlink()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock() -> None:
    paths.lock_path().unlink(missing_ok=True)


def _is_limit_error(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in LIMIT_ERROR_MARKERS)


def claude_path() -> str | None:
    """Find the claude binary. Schedulers run with a minimal PATH, so
    checking PATH alone is not enough."""
    found = shutil.which("claude")
    if found:
        return found
    home = os.path.expanduser("~")
    candidates = [
        f"{home}/.local/bin/claude",
        f"{home}/.claude/local/claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def run_job(job: store.Job, cfg: Config) -> store.Job:
    """Run one job through `claude -p`. Returns the updated job."""
    claude = claude_path()
    if not claude:
        return store.mark(job, store.FAILED, error="`claude` CLI not found on PATH")
    store.mark(job, store.RUNNING)
    cmd = [
        claude, "-p", PROMPT_TEMPLATE.format(prompt=job.prompt),
        "--output-format", "json",
        "--model", cfg.model,
        "--allowedTools", "WebSearch,WebFetch",
        *cfg.extra_args,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=cfg.job_timeout_minutes * 60,
            cwd=paths.scratch_dir(),
        )
    except subprocess.TimeoutExpired:
        return store.mark(job, store.FAILED, error=f"timed out after {cfg.job_timeout_minutes}m")
    except FileNotFoundError:
        return store.mark(job, store.FAILED, error="`claude` CLI not found on PATH")

    output = proc.stdout.strip()
    result_text, is_error = _parse_claude_output(output, proc)
    if is_error:
        error = result_text or proc.stderr.strip() or f"claude exited {proc.returncode}"
        if _is_limit_error(error):
            # Requeue: the batch should stop, and this job runs next window.
            return store.mark(job, store.PENDING, error=f"hit limit: {error[:200]}")
        return store.mark(job, store.FAILED, error=error[:500])

    result_path = _write_result(job, result_text)
    return store.mark(job, store.DONE, result_path=str(result_path), error=None)


def _parse_claude_output(output: str, proc) -> tuple[str, bool]:
    try:
        data = json.loads(output)
        return data.get("result", ""), bool(data.get("is_error")) or proc.returncode != 0
    except json.JSONDecodeError:
        # Not JSON — treat raw stdout as the answer if exit was clean.
        return output, proc.returncode != 0 or not output


def _write_result(job: store.Job, text: str):
    day_dir = paths.results_dir() / datetime.now().strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{job.id}-{store.slug(job.prompt)}.md"
    header = (
        f"# {job.prompt}\n\n"
        f"> Queued {job.created_at} · answered {datetime.now().isoformat(timespec='seconds')} "
        f"· by [claude-overnight](https://github.com/rohanprichard/claude-overnight)\n\n---\n\n"
    )
    path.write_text(header + text + "\n")
    return path


def _update_index(batch: list[store.Job]) -> None:
    index = paths.results_dir() / "index.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n## Batch {stamp}\n"]
    for job in batch:
        if job.status == store.DONE and job.result_path:
            rel = os.path.relpath(job.result_path, paths.results_dir())
            lines.append(f"- ✅ [{job.prompt[:80]}]({rel})")
        elif job.status == store.PENDING:
            lines.append(f"- ⏸️ requeued (hit limit): {job.prompt[:80]}")
        else:
            lines.append(f"- ❌ {job.prompt[:80]} — {job.error or 'failed'}")
    existing = index.read_text() if index.exists() else "# Overnight results\n"
    index.write_text(existing + "\n".join(lines) + "\n")


def run_batch(cfg: Config, force: bool = False, now: datetime | None = None) -> str:
    """Entry point for the scheduler tick and `overnight run`."""
    fixed_clock = now is not None
    now = now or datetime.now()
    pending = [j for j in store.list_jobs(store.PENDING) if j.attempts < cfg.max_attempts]
    if not pending:
        return "queue empty"
    if not _acquire_lock():
        return "another runner is active"
    try:
        usage = limits.fetch_usage()
        decision = should_start(cfg, usage, now, force)
        if not decision.run:
            return f"not running: {decision.reason}"

        batch: list[store.Job] = []
        for job in pending:
            job = run_job(job, cfg)
            batch.append(job)
            if job.status == store.PENDING:  # hit a limit mid-batch
                break
            check_time = now if fixed_clock else datetime.now()
            decision = should_continue(cfg, limits.fetch_usage(), check_time, force)
            if not decision.run:
                break

        _update_index(batch)
        done = sum(1 for j in batch if j.status == store.DONE)
        failed = sum(1 for j in batch if j.status == store.FAILED)
        left = len(store.list_jobs(store.PENDING))
        summary = f"{done} done, {failed} failed, {left} still queued"
        notify.send("claude-overnight", f"Batch finished: {summary}")
        return summary
    finally:
        _release_lock()
