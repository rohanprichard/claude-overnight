---
description: Queue a question or coding task for claude-overnight to run when your limits reset
allowed-tools: Bash(overnight add:*), Bash(overnight trust:*)
---

Queue the user's request for the overnight batch:

- If it is a research question, run `overnight add "$ARGUMENTS"`.
- If it is a coding task for the current project (implement/fix/refactor
  something here), run `overnight add --repo "$(pwd)" "$ARGUMENTS"`.
  If the output warns the repo is not trusted, ask the user whether to trust
  it, and on yes run `overnight trust "$(pwd)"`.

Then confirm it was queued and mention it will run in the next overnight
window (coding jobs land on an `overnight/*` branch to review in the morning).
