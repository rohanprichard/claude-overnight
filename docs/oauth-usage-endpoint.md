# Reading Claude Code usage limits programmatically

Reference documentation for `GET https://api.anthropic.com/api/oauth/usage` —
the undocumented endpoint that returns your Claude subscription's 5-hour and
weekly utilization.

This is a community reference, not official documentation. Anthropic does not
publish this endpoint and may change or remove it without notice. Everything
below was determined by observation and is kept current against what
[claude-overnight](https://github.com/rohanprichard/claude-overnight) sees in
production; corrections via issue or PR are welcome.

**What this is:** reading your own usage, with your own locally-stored token,
against Anthropic's own API. It is the same call Claude Code's `/usage` makes.
Nothing is bypassed, extended, or shared.

---

## Why you'd want it

Claude Code Pro/Max plans have a rolling 5-hour limit and a weekly limit.
Nothing in the CLI exposes those numbers to a script, so any tool that wants
to make decisions based on remaining quota — usage monitors, menubar
trackers, schedulers, auto-retry wrappers — needs this endpoint.

There is a second source: Claude Code ≥ 2.1.80 passes the same data to
statusline scripts on stdin. That is easier and more stable, but only works
inside an interactive session — it is unavailable to a background process, a
cron job, or anything running headless.

## Authentication

The endpoint takes the OAuth access token Claude Code already stores locally.
Two locations, in the order you should try them:

**1. Credentials file** (Linux, and some macOS installs)

```
~/.claude/.credentials.json
```

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-..."
  }
}
```

**2. macOS Keychain**

```sh
security find-generic-password -s "Claude Code-credentials" -w
```

The service name is exactly `Claude Code-credentials`, space included. The
command returns the same JSON structure as the file, so parse it identically.

Read the file first and fall back to the Keychain: the file check is cheap and
cannot trigger a Keychain permission prompt.

## The request

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <accessToken>
anthropic-beta: oauth-2025-04-20
```

The `anthropic-beta` header is required. Without it the request fails.

```sh
TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])')

curl -s https://api.anthropic.com/api/oauth/usage \
  -H "Authorization: Bearer $TOKEN" \
  -H "anthropic-beta: oauth-2025-04-20" | python3 -m json.tool
```

## Response shapes

**Two shapes exist.** The payload changed once already, in mid-2026, and any
consumer that handles only one will break when it changes again. Parse both.

### Modern: a `limits` array

```json
{
  "limits": [
    {"kind": "session",        "percent": 27.5, "resets_at": "2026-07-27T09:00:00Z"},
    {"kind": "weekly_scoped",  "percent": 61.2, "resets_at": "2026-07-30T00:00:00Z"},
    {"kind": "weekly_scoped",  "percent": 12.0, "resets_at": "2026-07-30T00:00:00Z"}
  ]
}
```

- `kind: "session"` is the rolling 5-hour window.
- `kind` beginning with `"weekly"` is a weekly limit. **There can be several**
  — they are scoped per model. Match on the `weekly` prefix rather than the
  exact string, since the suffix varies.
- `percent` is utilization consumed, 0–100. Higher means less remaining.
- `resets_at` is ISO 8601.

### Legacy: top-level objects

```json
{
  "five_hour":  {"utilization": 27.5, "resets_at": "2026-07-27T09:00:00Z"},
  "seven_day":  {"utilization": 61.2, "resets_at": "2026-07-30T00:00:00Z"}
}
```

Note the field is `utilization` here and `percent` in the modern shape. Same
meaning.

## Gotchas

**Multiple weekly entries.** When weekly limits are scoped per model you get
one entry per scope. Take the **highest** active one: any exhausted scope
blocks that model, so the maximum is what constrains you. Averaging or taking
the first will tell you that you have quota when you don't.

**Failure is "unknown", not "zero".** A missing token, an expired token, a
network failure, or a shape change all produce no usable number. If your code
treats that as 0% used, it will happily run at full tilt into a wall. Return an
explicit "unknown" and let callers decide — most should proceed cautiously
rather than either halting or assuming the best.

**Tokens expire.** The stored token is refreshed by Claude Code itself. Read it
fresh on every call rather than caching it at process start; a long-running
daemon that caches will start getting 401s.

**Don't rely on it alone.** Because it can vanish, pair it with a fallback that
detects limit exhaustion from `claude -p` output — matching on strings like
`usage limit`, `rate limit`, `limit reached`, `out of quota`. That way losing
the endpoint degrades your tool instead of breaking it.

**Percent is consumed, not remaining.** Easy to invert by accident.

## Reference implementation

A defensive parser handling both shapes, roughly 70 lines of dependency-free
Python:
[`src/overnight/limits.py`](../src/overnight/limits.py)

The parts worth copying are `parse_usage()` (handles both payloads and the
multiple-weekly case) and `fetch_usage()` (returns `None` on any failure rather
than raising or guessing).

## Other tools reading this data

- [ccusage](https://github.com/ccusage/ccusage) — token usage and costs from local JSONL
- [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) — real-time monitor with predictions
- [claude-overnight](https://github.com/rohanprichard/claude-overnight) — runs queued work when limits reset

If you maintain something that reads this endpoint and the shapes above are
wrong or incomplete, please open an issue. The point of this document is to
stop each of us rediscovering it separately.
