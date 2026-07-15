"""The `overnight` command."""

import argparse
import sys
from datetime import datetime

from . import __version__, config, install, limits, paths, runner, store


def cmd_add(args) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("Nothing to queue. Usage: overnight add \"your question\"")
        return 1
    job = store.add(prompt)
    print(f"Queued [{job.id}]: {prompt[:100]}")
    print("It will run in the next overnight window. `overnight status` to check.")
    return 0


def cmd_list(args) -> int:
    jobs = store.list_jobs()
    if not jobs:
        print("Queue is empty. Add with: overnight add \"your question\"")
        return 0
    for job in jobs:
        line = f"[{job.id}] {job.status:8} {job.prompt[:90]}"
        if job.error:
            line += f"  ({job.error[:60]})"
        print(line)
    return 0


def cmd_remove(args) -> int:
    if store.remove(args.id):
        print(f"Removed {args.id}")
        return 0
    print(f"No job with id {args.id}")
    return 1


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
        print(f"Limits: 5h {_fmt_pct(usage.five_hour_pct)} (resets {usage.five_hour_resets_at or '?'})  "
              f"weekly {_fmt_pct(usage.seven_day_pct)} (resets {usage.seven_day_resets_at or '?'})")
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


def cmd_run(args) -> int:
    cfg = config.load()
    result = runner.run_batch(cfg, force=args.force)
    print(result)
    return 0


def cmd_install(args) -> int:
    paths.ensure_dirs()
    config.load()  # writes default config on first run
    plist = install.install_launchd()
    cmd = install.install_slash_command()
    print(f"Installed launchd agent: {plist}")
    print(f"Installed slash command: {cmd}  (use /queue inside Claude Code)")
    print(f"Config: {paths.config_path()}")
    return 0


def cmd_uninstall(args) -> int:
    install.uninstall_launchd()
    install.uninstall_slash_command()
    print("Removed launchd agent and slash command. Queue and results kept in "
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

    p = sub.add_parser("add", help="queue a question")
    p.add_argument("prompt", nargs="+")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="show the queue")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("remove", help="remove a job by id")
    p.add_argument("id")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("status", help="show limits, queue and whether a batch would run")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="run the batch now if conditions allow")
    p.add_argument("--force", action="store_true", help="ignore window and limit checks")
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
