"""The batch runner: decides whether to run, executes jobs via `claude -p`,
writes markdown reports and a rolling index."""

import glob
import json
import os
import shutil
import subprocess
import time as time_mod
from dataclasses import dataclass
from datetime import datetime

from . import limits, notify, paths, store, trust
from .config import Config, in_window

PROMPT_TEMPLATE = """\
You are running unattended overnight; nobody can answer questions, so make \
reasonable assumptions and state them. Research the question below using web \
search where useful, and produce a complete, self-contained markdown report. \
Start with a short executive summary, then the details, then a Sources \
section with links. Return the report as your final response text — you have \
no file-write permissions here, so never try to save it to a file or ask for \
approval.

Question:
{prompt}
"""

REPO_PROMPT_TEMPLATE = """\
You are running unattended overnight in a fresh git worktree on a dedicated \
branch; nobody can answer questions, so make reasonable assumptions and state \
them. Implement the task below. Follow the project's existing conventions, \
run the test suite if you can find one, and do not push, merge, or touch \
anything outside this worktree. When you are done (or blocked), write a \
SUMMARY.md at the worktree root covering: what you did, what you did not do, \
test results, and what the reviewer should look at first.

Task:
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
    checking PATH alone is not enough — and claude's auto-updater can leave
    ~/.local/bin/claude as a dangling symlink mid-update, so fall back to
    the newest installed version directly."""
    found = shutil.which("claude")
    if found and os.path.isfile(found):
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
    versions = glob.glob(f"{home}/.local/share/claude/versions/*")
    for path in sorted(versions, reverse=True):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _invoke_claude(cmd: list[str], cwd, timeout_minutes: int) -> tuple[str, str | None, str | None]:
    """Run claude and return (result_text, error, session_id).
    error is None on success; session_id is kept even on failure so the
    session can be resumed interactively."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_minutes * 60, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return "", f"timed out after {timeout_minutes}m", None
    except FileNotFoundError:
        return "", "`claude` CLI not found on PATH", None
    output = proc.stdout.strip()
    session_id = None
    try:
        session_id = json.loads(output).get("session_id")
    except json.JSONDecodeError:
        pass
    result_text, is_error = _parse_claude_output(output, proc)
    if is_error:
        return result_text, result_text or proc.stderr.strip() or f"claude exited {proc.returncode}", session_id
    return result_text, None, session_id


def run_job(job: store.Job, cfg: Config) -> store.Job:
    """Run one job through `claude -p`. Returns the updated job."""
    claude = claude_path()
    if not claude:
        return store.mark(job, store.FAILED, error="`claude` CLI not found on PATH")
    if job.repo:
        return _run_repo_job(job, cfg, claude)

    store.mark(job, store.RUNNING)
    resume = job.extra.get("resume_session")
    prompt = job.prompt if resume else PROMPT_TEMPLATE.format(prompt=job.prompt)
    cmd = [
        claude, "-p", prompt,
        *(["--resume", resume] if resume else []),
        "--output-format", "json",
        "--model", job.model or cfg.model,
        "--allowedTools", "WebSearch,WebFetch",
        *cfg.extra_args,
    ]
    result_text, error, session_id = _invoke_claude(cmd, paths.scratch_dir(), cfg.job_timeout_minutes)
    if session_id:
        job.extra["session_id"] = session_id
    if error:
        if _is_limit_error(error):
            # Requeue: the batch should stop, and this job runs next window.
            return store.mark(job, store.PENDING, error=f"hit limit: {error[:200]}")
        return store.mark(job, store.FAILED, error=error[:500])

    result_path = _write_result(job, result_text)
    return store.mark(job, store.DONE, result_path=str(result_path), error=None)


def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _run_repo_job(job: store.Job, cfg: Config, claude: str) -> store.Job:
    repo = os.path.realpath(os.path.expanduser(job.repo))
    if not os.path.isdir(os.path.join(repo, ".git")):
        return store.mark(job, store.FAILED, error=f"not a git repo: {repo}")
    if not trust.is_trusted(repo):
        return store.mark(
            job, store.FAILED,
            error=f"repo not trusted; run: overnight trust {repo}")

    resume = job.extra.get("resume_session")
    if resume and job.extra.get("branch"):
        # Follow-up: continue on the parent job's branch.
        branch = job.extra["branch"]
        branch_args = [branch]
    else:
        resume = None
        branch = f"overnight/{store.slug(job.prompt, 30)}-{job.id[-6:]}"
        branch_args = ["-b", branch]
    worktree = paths.base_dir() / "worktrees" / job.id
    added = _git(repo, "worktree", "add", str(worktree), *branch_args)
    if added.returncode != 0:
        return store.mark(job, store.FAILED,
                          error=f"worktree add failed: {added.stderr.strip()[:300]}")

    store.mark(job, store.RUNNING)
    try:
        prompt = job.prompt if resume else REPO_PROMPT_TEMPLATE.format(prompt=job.prompt)
        cmd = [
            claude, "-p", prompt,
            *(["--resume", resume] if resume else []),
            "--output-format", "json",
            "--model", job.model or cfg.model,
            "--permission-mode", "acceptEdits",
            *cfg.extra_args,
        ]
        result_text, error, session_id = _invoke_claude(cmd, worktree, cfg.repo_job_timeout_minutes)
        if session_id:
            job.extra["session_id"] = session_id

        if error and _is_limit_error(error):
            return store.mark(job, store.PENDING, error=f"hit limit: {error[:200]}")

        _git(worktree, "add", "-A")
        prefix = "WIP overnight" if error else "overnight"
        committed = _git(worktree, "commit", "-m", f"{prefix}: {job.prompt[:70]}")
        has_commit = committed.returncode == 0
        diffstat = ""
        if has_commit:
            diffstat = _git(worktree, "show", "--stat", "--format=", "HEAD").stdout.strip()

        if error and not has_commit:
            return store.mark(job, store.FAILED, error=error[:500])

        body = (
            f"**Branch:** `{branch}` in `{repo}`\n\n"
            + (f"**Job error (WIP branch kept):** {error[:300]}\n\n" if error else "")
            + (f"```\n{diffstat}\n```\n\n" if diffstat else "*No file changes were made.*\n\n")
            + (result_text or "")
        )
        result_path = _write_result(job, body)
        status = store.FAILED if error else store.DONE
        job.extra.update({"branch": branch, "repo": repo})
        return store.mark(job, status, result_path=str(result_path),
                          error=error[:500] if error else None,
                          extra=job.extra)
    finally:
        _git(repo, "worktree", "remove", "--force", str(worktree))
        # If nothing was committed the branch is pointless; drop it quietly.
        head = _git(repo, "rev-parse", branch)
        base = _git(repo, "rev-parse", "HEAD")
        if head.returncode == 0 and head.stdout.strip() == base.stdout.strip():
            _git(repo, "branch", "-D", branch)


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
            lines.append(f"- ✅ [{job.prompt[:80]}]({rel}) · resume `{job.id[-6:]}`")
        elif job.status == store.PENDING:
            lines.append(f"- ⏸️ requeued (hit limit): {job.prompt[:80]}")
        else:
            lines.append(f"- ❌ {job.prompt[:80]} — {job.error or 'failed'}")
    existing = index.read_text() if index.exists() else "# Overnight results\n"
    index.write_text(existing + "\n".join(lines) + "\n")


def is_due(job: store.Job, now: datetime) -> bool:
    return not job.not_before or job.not_before <= now.date().isoformat()


def resume_target(job: store.Job) -> tuple[str, str]:
    """Where and what to resume for a finished job: returns (cwd, session_id).
    Raises ValueError with a user-facing message when resuming isn't possible."""
    session_id = job.extra.get("session_id")
    if not session_id:
        raise ValueError("no session recorded for this job (ran before v0.4, or claude produced no output)")
    if not job.repo:
        return str(paths.scratch_dir()), session_id

    repo = job.extra.get("repo", job.repo)
    branch = job.extra.get("branch")
    worktree = paths.base_dir() / "worktrees" / job.id
    if not worktree.exists():
        if not branch:
            raise ValueError("no branch recorded for this repo job")
        # Recreate the worktree at its original path so the claude session's
        # project directory matches.
        added = _git(repo, "worktree", "add", str(worktree), branch)
        if added.returncode != 0:
            raise ValueError(f"could not recreate worktree: {added.stderr.strip()[:200]}")
    return str(worktree), session_id


def run_batch(cfg: Config, force: bool = False, now: datetime | None = None) -> str:
    """Entry point for the scheduler tick and `overnight run`."""
    fixed_clock = now is not None
    now = now or datetime.now()
    pending = [j for j in store.list_jobs(store.PENDING)
               if j.attempts < cfg.max_attempts and is_due(j, now)]
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
