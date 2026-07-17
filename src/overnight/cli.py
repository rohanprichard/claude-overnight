"""The `overnight` command."""

import argparse
import os
import sys
from datetime import datetime

from . import __version__, config, install, limits, paths, runner, store, trust


def cmd_add(args) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("Nothing to queue. Usage: overnight add \"your question\"")
        return 1
    job = store.add(prompt, repo=args.repo, model=args.model, first=args.first)
    kind = "coding job" if args.repo else "question"
    print(f"Queued {kind} [{job.id}]: {prompt[:100]}")
    if args.repo and not trust.is_trusted(args.repo):
        print(f"⚠️  {args.repo} is not trusted yet — the job will fail unless you run:")
        print(f"    overnight trust {args.repo}")
    print("It will run in the next overnight window. `overnight status` to check.")
    return 0


def cmd_list(args) -> int:
    jobs = store.list_jobs()
    if not jobs:
        print("Queue is empty. Add with: overnight add \"your question\"")
        return 0
    for job in jobs:
        tags = ""
        if job.repo:
            tags += f" repo={job.repo}"
        if job.model:
            tags += f" model={job.model}"
        if job.priority:
            tags += " first"
        line = f"[{job.id}] {job.status:8} {job.prompt[:80]}{tags}"
        if job.error:
            line += f"  ({job.error[:60]})"
        print(line)
    return 0


def cmd_trust(args) -> int:
    if args.repo:
        canonical = trust.trust(args.repo)
        print(f"Trusted for overnight coding jobs: {canonical}")
        return 0
    trusted = trust.list_trusted()
    if not trusted:
        print("No trusted repos. Add one with: overnight trust <path>")
    for repo in trusted:
        print(repo)
    return 0


def cmd_untrust(args) -> int:
    if trust.untrust(args.repo):
        print(f"Untrusted: {args.repo}")
        return 0
    print(f"Was not trusted: {args.repo}")
    return 1


def cmd_results(args) -> int:
    if args.id:
        job = store.find(args.id)
        if not job or not job.result_path:
            print(f"No result for {args.id}")
            return 1
        print(open(job.result_path).read())
        if job.extra.get("session_id"):
            print(f"\n→ continue this conversation: overnight resume {job.id[-6:]}")
        return 0
    index = paths.results_dir() / "index.md"
    if not index.exists():
        print("No results yet.")
        return 0
    print(index.read_text())
    done = store.list_jobs(store.DONE)
    if done:
        print("Read one report: overnight results <id> · pick up where it left off: overnight resume <id>")
        for job in done[-5:]:
            print(f"  {job.id[-6:]}  {job.prompt[:70]}")
    return 0


def cmd_resume(args) -> int:
    job = store.find(args.id)
    if not job:
        print(f"No job matching '{args.id}'. Try: overnight list")
        return 1
    try:
        cwd, session_id = runner.resume_target(job)
    except ValueError as e:
        print(f"Can't resume: {e}")
        return 1
    claude = runner.claude_path()
    if not claude:
        print("`claude` CLI not found.")
        return 1
    print(f"Resuming overnight session for: {job.prompt[:70]}")
    if job.repo:
        print(f"(worktree: {cwd} — branch {job.extra.get('branch')})")
    os.chdir(cwd)
    os.execv(claude, [claude, "--resume", session_id])


def cmd_remove(args) -> int:
    if store.remove(args.id):
        print(f"Removed {args.id}")
        return 0
    print(f"No job with id {args.id}")
    return 1


def cmd_retry(args) -> int:
    failed = store.list_jobs(store.FAILED)
    if not failed:
        print("No failed jobs.")
        return 0
    for job in failed:
        job.attempts = 0
        job.error = None
        job.status = store.PENDING
        store.save(job)
        print(f"Requeued [{job.id}]: {job.prompt[:80]}")
    return 0


def cmd_status(args) -> int:
    cfg = config.load()
    usage = limits.fetch_usage()
    print(f"claude-overnight {__version__}")
    print(f"Window: {cfg.window_start:%H:%M}-{cfg.window_end:%H:%M}  "
          f"start<={cfg.start_max_utilization:.0f}%  stop>={cfg.stop_utilization:.0f}%  "
          f"weekly<={cfg.weekly_max_utilization:.0f}%")
    if usage is None:
        print("Limits: unavailable (no token or endpoint unreachable) — runner will try optimistically")
    else:
        print(f"Limits: 5h {_fmt_pct(usage.five_hour_pct)} (resets {_fmt_reset(usage.five_hour_resets_at)})  "
              f"weekly {_fmt_pct(usage.seven_day_pct)} (resets {_fmt_reset(usage.seven_day_resets_at)})")
    pending = store.list_jobs(store.PENDING)
    done = store.list_jobs(store.DONE)
    failed = store.list_jobs(store.FAILED)
    print(f"Queue: {len(pending)} pending, {len(done)} done, {len(failed)} failed")
    decision = runner.should_start(cfg, usage, datetime.now())
    print(f"Would run now? {'yes' if decision.run else 'no'} — {decision.reason}")
    print(f"Results: {paths.results_dir() / 'index.md'}")
    return 0


def _fmt_pct(value) -> str:
    return f"{value:.0f}%" if value is not None else "?"


def _fmt_reset(value: str | None) -> str:
    if not value:
        return "?"
    try:
        dt = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return value
    if dt.date() == datetime.now().astimezone().date():
        return dt.strftime("%H:%M")
    return dt.strftime("%a %H:%M")


def cmd_run(args) -> int:
    cfg = config.load()
    if args.dry_run:
        return _dry_run(cfg)
    result = runner.run_batch(cfg, force=args.force)
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {result}")
    return 0


def _dry_run(cfg) -> int:
    now = datetime.now()
    usage = limits.fetch_usage()
    print(f"time            {now:%H:%M} — window {cfg.window_start:%H:%M}-{cfg.window_end:%H:%M} "
          f"({'inside' if config.in_window(cfg, now.time()) else 'outside'})")
    if usage is None:
        print("limits          unreadable → would proceed optimistically")
    else:
        print(f"5h window       {_fmt_pct(usage.five_hour_pct)} (start cap {cfg.start_max_utilization:.0f}%, "
              f"stop cap {cfg.stop_utilization:.0f}%)")
        print(f"weekly          {_fmt_pct(usage.seven_day_pct)} (cap {cfg.weekly_max_utilization:.0f}%)")
    pending = [j for j in store.list_jobs(store.PENDING) if j.attempts < cfg.max_attempts]
    exhausted = [j for j in store.list_jobs(store.PENDING) if j.attempts >= cfg.max_attempts]
    print(f"queue           {len(pending)} runnable, {len(exhausted)} out of attempts")
    for job in pending:
        note = ""
        if job.repo:
            note = " ✓ trusted" if trust.is_trusted(job.repo) else " ✗ NOT TRUSTED (will fail)"
            note = f" [repo: {job.repo}{note}]"
        print(f"  - {job.prompt[:70]}{note}")
    decision = runner.should_start(cfg, usage, now)
    print(f"verdict         would {'RUN' if decision.run else 'NOT run'} — {decision.reason}")
    return 0


def cmd_install(args) -> int:
    paths.ensure_dirs()
    config.load()  # writes default config on first run
    plist = install.install_scheduler()
    cmd = install.install_slash_command()
    print(f"Installed scheduler: {plist}")
    print(f"Installed slash command: {cmd}  (use /queue inside Claude Code)")
    print(f"Config: {paths.config_path()}")
    return 0


def cmd_uninstall(args) -> int:
    install.uninstall_scheduler()
    install.uninstall_slash_command()
    print("Removed scheduler and slash command. Queue and results kept in "
          f"{paths.base_dir()}")
    return 0


def cmd_config(args) -> int:
    config.load()
    print(paths.config_path())
    print()
    print(paths.config_path().read_text())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="overnight",
        description="Queue research questions all day. Wake up to answers.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="queue a question or coding task")
    p.add_argument("prompt", nargs="+")
    p.add_argument("--repo", help="run as a coding job in a worktree of this git repo (must be trusted)")
    p.add_argument("--model", help="model for this job (overrides config)")
    p.add_argument("--first", action="store_true", help="run before normal-priority jobs")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="show the queue")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("trust", help="trust a repo for coding jobs (no arg: list trusted)")
    p.add_argument("repo", nargs="?")
    p.set_defaults(func=cmd_trust)

    p = sub.add_parser("untrust", help="remove a repo from the trust list")
    p.add_argument("repo")
    p.set_defaults(func=cmd_untrust)

    p = sub.add_parser("results", help="print the results digest, or one job's report")
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_results)

    p = sub.add_parser("resume", help="open an interactive claude session where an overnight job left off")
    p.add_argument("id", help="job id or any unambiguous fragment of it")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("remove", help="remove a job by id")
    p.add_argument("id")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("retry", help="requeue all failed jobs")
    p.set_defaults(func=cmd_retry)

    p = sub.add_parser("status", help="show limits, queue and whether a batch would run")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="run the batch now if conditions allow")
    p.add_argument("--force", action="store_true", help="ignore window and limit checks")
    p.add_argument("--dry-run", action="store_true", help="explain what would happen without running")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("install", help="set up the launchd agent and /queue slash command")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="remove the launchd agent and slash command")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("config", help="print config path and contents")
    p.set_defaults(func=cmd_config)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
