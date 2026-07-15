---
description: Queue a question for claude-overnight to research when your limits reset
allowed-tools: Bash(overnight add:*), Bash(overnight status:*)
---

Queue the user's question for overnight research.

1. Run `overnight add "$ARGUMENTS"`.
2. If the command is not found, tell the user to install the CLI first:
   `uv tool install claude-overnight && overnight install`.
3. On success, confirm the question was queued and mention it will run in
   the next overnight window (they can check with `overnight status`).
