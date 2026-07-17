# claude-overnight

**Queue research questions all day. Wake up to answers.**

![demo](assets/demo.gif)

Your Claude Code weekly limit quietly expires while you sleep — if you hit the 5-hour cap every day, you still leave weekly quota on the table every single night. `claude-overnight` puts that idle quota to work: queue questions with `/queue` during the day, and a scheduler runs them headlessly inside your configured night window, when your limits have reset. You wake up to a folder of markdown research reports and a morning digest.

```
you (2:14 pm) ──▶ /queue what are the tradeoffs of CRDTs vs OT for a collab editor?
you (5:40 pm) ──▶ /queue compare litestream vs. postgres logical replication for a side project

              💤  3:00 am — limits reset, window open, batch runs

you (8:05 am) ──▶ ~/.overnight/results/index.md
                  ✅ tradeoffs of CRDTs vs OT — crdts-vs-ot.md
                  ✅ litestream vs postgres replication — litestream-vs-postgres.md
```

## Why

- **Limit-aware, not just time-aware.** Cron can run Claude at 3am, but it doesn't know whether your 5-hour window is fresh or your weekly cap is nearly gone. `claude-overnight` checks both before starting and *between every job*, and stops at a configurable threshold so you wake up with quota left for actual work.
- **Runs on your subscription, unattended.** Jobs execute through `claude -p` (headless mode) with tools restricted to web search — no API key, no extra cost.
- **Zero dependencies.** Pure Python standard library. `uv tool install claude-overnight` and you're done.

## Install

```sh
uv tool install claude-overnight   # or: pipx install claude-overnight
overnight install                  # sets up the scheduler + /queue slash command
```

`overnight install` does two things:

1. Registers a **scheduler** — a launchd agent on macOS, a systemd user timer on Linux — that wakes every 30 minutes, checks whether you're inside the night window and under the limit thresholds, and runs the queue if so.
2. Drops a **`/queue` slash command** into `~/.claude/commands/`, so you can queue questions without leaving Claude Code.

Requires macOS or Linux, Python 3.11+, and the [Claude Code](https://code.claude.com) CLI with a Pro/Max subscription. Also installable as a Claude Code plugin (`/plugin marketplace add rohanprichard/claude-overnight`) or an agent skill (`npx skills add rohanprichard/claude-overnight`).

## Use

```sh
# from anywhere
overnight add "how do sqlite WAL checkpoints actually work?"

# or inside any Claude Code session
/queue how do sqlite WAL checkpoints actually work?

overnight list          # see the queue
overnight status        # current 5h/weekly utilization + would-it-run-now
overnight results       # read the digest (or one report: overnight results <id>)
overnight resume <id>   # open an interactive claude session where the job left off
overnight followup <id> "go deeper on X"   # queue a continuation for the next window
overnight run --dry-run # explain exactly what would happen and why
overnight run --force   # run the batch right now, ignoring window/limits
overnight retry         # requeue failed jobs
```

Per-job flags: `--model opus` to override the model, `--first` to jump the queue.

## Overnight coding jobs

Beyond research questions, you can queue actual work against a repo:

```sh
overnight trust ~/code/myapp              # one-time, per repo
overnight add --repo ~/code/myapp "add a dark mode toggle to settings; follow the existing theme pattern and run the tests"
```

Or from a Claude Code session inside the repo, just `/queue add a dark mode toggle...` — the command detects it's a coding task and captures the repo automatically.

Overnight, the job runs in a **fresh git worktree on a dedicated branch** — your working tree, uncommitted changes, and checked-out branch are never touched. In the morning:

```
git diff main..overnight/add-a-dark-mode-toggle-3f9c2a   # love it or delete it
```

The agent commits its work (WIP-prefixed if it got stuck), writes a `SUMMARY.md`, and the digest shows the branch plus a diffstat. Branches with no changes are dropped automatically.

**Safety model:** coding jobs run with `acceptEdits` (they need to edit files and run your tests), so they only run against repos you've explicitly blessed with `overnight trust`. The worktree fences file changes, but a job can execute shell commands — trust repos accordingly. Research jobs remain locked to web-search tools.

Results land in `~/.overnight/results/<date>/`, one markdown report per question, with a rolling `index.md` digest. A notification fires when the batch finishes.

**Every overnight job saves its Claude session**, which enables overnight *threads* instead of one-shot answers:

- `overnight resume <id>` (any unambiguous id fragment) drops you into the conversation that produced the result — ask follow-ups, challenge conclusions, redirect the work, with all the overnight context loaded. For coding jobs it recreates the worktree on the job's branch first, so "change the approach" picks up mid-stream.
- `overnight followup <id> "now compare against Yjs specifically"` queues a *continuation* of that session for the next window. Read at breakfast, redirect, sleep, repeat. Follow-ups to coding jobs continue on the same branch.
- `overnight add --after 2026-07-21 "..."` holds a job until a given date ("research this before Monday's meeting").

## Configure

`~/.overnight/config.toml`:

```toml
[window]
start = "01:00"   # jobs only run between these local times
end = "07:00"     # windows may cross midnight ("23:00" → "06:00")

[limits]
start_max_utilization = 20   # don't start if the 5h window is already >20% used
stop_utilization = 60        # stop the batch once 5h usage crosses 60%
weekly_max_utilization = 80  # never run if the weekly limit is >80% used

[run]
model = "sonnet"
job_timeout_minutes = 15       # research jobs
repo_job_timeout_minutes = 45  # coding jobs get time to build and test
max_attempts = 2
```

## How it works (there's no official API)

Claude Code doesn't expose a usage API — but it stores an OAuth token locally (macOS Keychain / `~/.claude/.credentials.json`), and the community discovered that `GET https://api.anthropic.com/api/oauth/usage` with that token returns your 5-hour and weekly utilization with reset timestamps. `claude-overnight` uses that to decide when it's safe to run.

Because the endpoint is **undocumented and could change**, everything degrades gracefully: if usage can't be read, the runner proceeds optimistically and detects limit errors from `claude -p` output instead — a job that hits the limit is requeued untouched for the next window, and the batch stops.

Full details in [docs/how-it-works.md](docs/how-it-works.md).

## Edge cases handled

- **Machine asleep at 3am** — launchd (and systemd with `Persistent=true`) runs the missed tick on wake, so the batch runs when you open the lid, still before you start working.
- **One job eating the whole window** — per-job timeouts plus utilization re-checks between jobs.
- **Two runners racing** — lockfile with stale-lock recovery.
- **Headless Claude wanting to ask you something** — the prompt template instructs it to make reasonable assumptions and state them.
- **Weekly cap already blown** — the runner skips the batch and says why in `overnight status`.

## Uninstall

```sh
overnight uninstall            # removes the scheduler + slash command
uv tool uninstall claude-overnight
rm -rf ~/.overnight            # queue, results, config
```

## Roadmap

- "Quota saved this week" stats in `overnight status`
- Digest delivery to Telegram/ntfy/email
- Pluggable backends: the queue, scheduler, and threshold logic are agent-agnostic — only the `claude -p` invocation and the limits reader are Claude-specific. Codex (`codex exec`) and Cursor CLI backends are on the table if there's demand.

## Related tools

- [ccusage](https://github.com/ryoppippi/ccusage) — analyze your Claude Code token usage and costs from local JSONL
- [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) — real-time usage monitor with predictions and warnings
- [claude-auto-retry](https://github.com/cheapestinference/claude-auto-retry) — auto-resume an interrupted session when the limit lifts

## License

MIT
