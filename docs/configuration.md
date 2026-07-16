# Configuration

Everything lives in `~/.overnight/config.toml`, created with defaults on first run (`overnight install` or any command). Set `OVERNIGHT_HOME` to relocate the whole state directory.

```toml
[window]
start = "01:00"
end = "07:00"

[limits]
start_max_utilization = 20
stop_utilization = 60
weekly_max_utilization = 80

[run]
model = "sonnet"
job_timeout_minutes = 15
max_attempts = 2
extra_args = []
```

## `[window]`

| Key | Default | Meaning |
| --- | --- | --- |
| `start`, `end` | `01:00` / `07:00` | Local times bounding when batches may run. `start = "23:00", end = "06:00"` crosses midnight and works as expected. |

Pick a window that starts *after* your last coding session's 5-hour window has reset, and ends *before* you start work. The runner ticks every 30 minutes inside the window, so a batch blocked at 1:00 (limits still hot) will retry at 1:30, 2:00, …

## `[limits]`

| Key | Default | Meaning |
| --- | --- | --- |
| `start_max_utilization` | `20` | Don't start a batch unless the 5-hour window is at most this % used. |
| `stop_utilization` | `60` | Stop the batch once 5-hour usage reaches this %. What's left is your morning buffer. |
| `weekly_max_utilization` | `80` | Never run if weekly usage exceeds this %. Protects your work-week quota. |

If usage can't be read at all (expired token, endpoint changed), the runner proceeds and stops on the first limit error instead.

## `[run]`

| Key | Default | Meaning |
| --- | --- | --- |
| `model` | `sonnet` | Passed to `claude --model`. Use `haiku` to stretch quota further, `opus` for depth. |
| `job_timeout_minutes` | `15` | Hard kill per research job. |
| `repo_job_timeout_minutes` | `45` | Hard kill per coding job (needs time to build/test). |
| `max_attempts` | `2` | Failed/limit-hit jobs are retried on later ticks up to this many times. |
| `extra_args` | `[]` | Extra flags appended to the `claude -p` invocation, e.g. `["--fallback-model", "haiku"]`. |

## Paths

| Path | Contents |
| --- | --- |
| `~/.overnight/queue/` | One JSON file per job |
| `~/.overnight/results/<date>/` | Markdown reports |
| `~/.overnight/results/index.md` | Rolling digest, newest batch last |
| `~/.overnight/logs/` | scheduler runner stdout/stderr |
| `~/.overnight/trusted_repos` | Repos blessed for coding jobs |
| `~/.overnight/worktrees/` | Transient worktrees during coding jobs |
| `~/Library/LaunchAgents/com.claude-overnight.runner.plist` | The scheduler (macOS) |
| `~/.config/systemd/user/claude-overnight.{service,timer}` | The scheduler (Linux) |
