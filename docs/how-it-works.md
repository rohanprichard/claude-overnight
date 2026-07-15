# How it works

There is no official API for Claude Code subscription limits. This document explains what `claude-overnight` does instead, so you can judge the tradeoffs yourself.

## Reading your limits

Claude Code authenticates Pro/Max subscriptions with an OAuth token it stores locally:

- **macOS Keychain**, service `Claude Code-credentials` (the default on Macs)
- `~/.claude/.credentials.json` (Linux, and some macOS setups)

The community discovered that this token works against an undocumented endpoint:

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <accessToken>
anthropic-beta: oauth-2025-04-20
```

The response contains a `limits` list with entries like:

```json
{ "kind": "session",       "percent": 27.5, "resets_at": "2026-07-15T09:29:59Z" }
{ "kind": "weekly_scoped", "percent": 44,   "resets_at": "2026-07-18T18:59:59Z",
  "scope": { "model": { "display_name": "Fable" } } }
```

- `session` is the rolling **5-hour window**.
- `weekly_scoped` entries are the **weekly limits**, potentially one per model. `claude-overnight` conservatively uses the highest active one.

Older accounts return a legacy shape (`five_hour` / `seven_day` objects with a `utilization` field); the parser handles both.

The token is **read at runtime and never stored, logged, or sent anywhere except `api.anthropic.com`** — the same place Claude Code itself sends it.

## Deciding when to run

A launchd agent ticks every 30 minutes. On each tick the runner checks, in order:

1. **Lockfile** — is another batch already running? (Stale locks older than 2 hours are cleared.)
2. **Night window** — is the local time inside `[window.start, window.end)`? Windows may cross midnight.
3. **Weekly cap** — is weekly utilization ≤ `weekly_max_utilization`? If your week is nearly spent, running overnight jobs would eat quota you'll want for real work.
4. **5-hour start cap** — is the 5-hour window ≤ `start_max_utilization`? A fresh window means the batch gets maximum room.

Between every job it re-checks, and stops once the 5-hour window crosses `stop_utilization` — the whole point is to use *surplus* quota, not to hand you an empty tank at 9am.

## Running jobs

Each job runs through Claude Code's headless mode:

```
claude -p "<wrapped prompt>" --output-format json --model sonnet --allowedTools "WebSearch,WebFetch"
```

- The wrapper instructs Claude that it is unattended: make reasonable assumptions, state them, and produce a self-contained markdown report with sources.
- Tools are restricted to web search/fetch; jobs run in an empty scratch directory, so they can't touch your projects.
- Each job has a timeout (default 15 minutes) and a max attempt count (default 2).

## Failure modes, by design

| What breaks | What happens |
| --- | --- |
| Usage endpoint changes or disappears | `fetch_usage()` returns `None`; the runner proceeds optimistically and relies on error detection instead |
| Token expired (Claude Code hasn't run in a while) | Same as above — and `claude -p` refreshes tokens itself when it runs |
| A job hits the usage limit mid-batch | The job is **requeued untouched**, the batch stops, and the next tick (or next night) retries |
| Mac asleep during the window | launchd runs the missed tick on wake |
| `claude` CLI missing | Job marked failed with a clear error |
| Two ticks overlap | Lockfile prevents the second runner |

## What this is not

- It does not bypass, extend, or game your limits — it only runs work you queued, on your own subscription, at times your quota would otherwise sit idle.
- It is not affiliated with Anthropic, and the usage endpoint could change without notice. The tool is built to degrade to "try and detect" rather than break.
