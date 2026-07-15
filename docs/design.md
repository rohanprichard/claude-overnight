# Design

*Spec for claude-overnight v0.1, 2026-07-15.*

## Problem

Claude Code Pro/Max plans have a rolling 5-hour limit and a weekly limit. Heavy users hit the 5-hour cap daily yet still leave weekly quota unused, because nights are idle. That surplus expires silently.

## Goal

Let a user queue research questions at any time, and run them unattended overnight — inside a configurable window, only when limits have actually reset, stopping before the fresh window is spent — with results delivered as markdown reports plus a digest.

**Non-goals (v0.1):** repo-scoped coding jobs, Linux/Windows support, priorities/dependencies between jobs, any server component.

## Architecture

Three pieces, one data directory (`~/.overnight`):

1. **CLI (`overnight`)** — queue management (`add/list/remove`), visibility (`status`), execution (`run`), setup (`install/uninstall`). Pure-stdlib Python 3.11+.
2. **`/queue` slash command + Claude Code plugin** — thin wrappers that shell out to `overnight add`, so queueing never requires leaving a session.
3. **Runner + launchd agent** — a 30-minute tick; each tick is idempotent and cheap when there's nothing to do (no queue, outside window, limits hot, or another runner holds the lock).

Module boundaries (`src/overnight/`):

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `paths` | filesystem layout, `OVERNIGHT_HOME` override | — |
| `config` | TOML config, window math | `paths` |
| `store` | job persistence (one JSON per job), status transitions | `paths` |
| `limits` | OAuth token discovery, usage endpoint, defensive parsing | — |
| `runner` | start/continue decisions, job execution, results, index, lock | all above |
| `notify` | best-effort macOS notification | — |
| `install` | launchd plist, slash command file | `paths` |
| `cli` | argument parsing only | all above |

## Key decisions

- **Decisions are pure functions** (`should_start`, `should_continue`) taking config + usage + clock, so the threshold logic is unit-testable without network or subprocesses.
- **Usage unknown ≠ usage zero.** `fetch_usage()` returns `None` on any failure and callers proceed optimistically, relying on limit-error detection in `claude -p` output. This is what keeps the tool alive if the undocumented endpoint changes.
- **Limit-hit jobs are requeued, not failed.** A job that ran into the cap did nothing wrong; it runs next window. The batch stops immediately.
- **One JSON file per job** instead of a single queue file: no read-modify-write races between `add` (interactive) and the runner; the runner's lockfile only guards batch execution.
- **Jobs run in a scratch cwd with tools restricted to `WebSearch,WebFetch`** — an unattended agent gets no access to the user's projects.

## Testing

32+ unit tests cover: store roundtrips, config parsing and midnight-crossing windows, both usage payload shapes (modern `limits` list, legacy `five_hour`/`seven_day`), start/continue threshold decisions, job success/failure/timeout/limit-requeue paths, batch behavior (index writing, mid-batch limit stop, lock contention, attempt exhaustion). The `claude` subprocess and the usage endpoint are mocked; `OVERNIGHT_HOME` isolates all filesystem state per test.
