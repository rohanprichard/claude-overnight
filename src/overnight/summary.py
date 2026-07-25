"""HTML summary of a finished batch, opened in the browser so mornings start
with one glance: what ran, what failed, and the command to resume each one."""

import html
import webbrowser
from datetime import datetime
from pathlib import Path

from . import paths, store

_ICON = {store.DONE: "✅", store.FAILED: "❌", store.PENDING: "⏸️"}


def write(batch: list[store.Job]) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = "\n".join(_row(job) for job in batch) or "<li>Nothing ran.</li>"
    path = paths.results_dir() / "latest.html"
    path.write_text(_PAGE.format(stamp=html.escape(stamp), rows=rows))
    return path


def open_in_browser(path: Path) -> None:
    try:
        webbrowser.open(f"file://{path}")
    except Exception:
        pass


def _row(job: store.Job) -> str:
    icon = _ICON.get(job.status, "•")
    prompt = html.escape(job.prompt[:120])
    short_id = job.id[-6:]
    if job.status == store.DONE:
        detail = f"<code>overnight resume {short_id}</code>"
        if job.result_path:
            detail += f' &middot; <a href="file://{job.result_path}">report</a>'
    elif job.status == store.FAILED:
        detail = html.escape((job.error or "failed")[:200])
    else:
        detail = "requeued (hit limit)"
    return f'<li>{icon} <span class="prompt">{prompt}</span><div class="detail">{detail}</div></li>'


_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>claude-overnight — {stamp}</title>
<style>
  body {{ font: 15px/1.5 -apple-system, BlinkMacSystemFont, sans-serif; max-width: 720px;
         margin: 40px auto; padding: 0 16px; background: #0d1117; color: #e6edf3; }}
  h1 {{ font-size: 18px; font-weight: 600; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 12px 0; border-bottom: 1px solid #21262d; }}
  .prompt {{ font-weight: 500; }}
  .detail {{ margin-top: 4px; font-size: 13px; color: #8b949e; }}
  code {{ background: #161b22; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>claude-overnight &middot; batch {stamp}</h1>
<ul>
{rows}
</ul>
</body>
</html>
"""
