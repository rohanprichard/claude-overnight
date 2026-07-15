---
name: claude-overnight
description: Queue research questions to run overnight when Claude Code usage limits reset. Use when the user wants to defer a question or research task ("queue this", "look into this tonight", "save this for later"), or when they are near their usage limit and the task is not urgent.
---

# claude-overnight

Queues questions for the `overnight` CLI, which runs them headlessly at night
when the user's Claude Code limits have reset, and saves markdown reports to
`~/.overnight/results/`.

## Queue a question

```sh
overnight add "the user's question, phrased as a self-contained research prompt"
```

Rephrase the question so it stands alone — the overnight run has no
conversation context. Include any constraints the user mentioned.

After queueing, confirm to the user and mention the report will be in
`~/.overnight/results/` after the next overnight window.

## If the command is missing

Tell the user to install it first:

```sh
uv tool install claude-overnight
overnight install
```

`overnight install` sets up the launchd scheduler. Without it, queued jobs
never run automatically (only via `overnight run --force`).

## Check status or results

- `overnight status` — current 5-hour/weekly utilization, queue counts, and
  whether a batch would run right now
- `overnight list` — queued/done/failed jobs
- `cat ~/.overnight/results/index.md` — the digest of finished reports

## When to suggest queueing proactively

If the user mentions hitting or nearing their usage limit and their request
is research-shaped (not an edit to this codebase), offer to queue it for the
overnight window instead of burning the remaining quota.
