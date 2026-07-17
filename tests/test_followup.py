import json
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from overnight import limits, runner, store
from overnight.config import Config

NIGHT = datetime(2026, 7, 18, 3, 0)


@pytest.fixture(autouse=True)
def claude_on_path(monkeypatch):
    monkeypatch.setattr(runner, "claude_path", lambda: "/fake/bin/claude")


def test_followup_inherits_session_repo_and_branch():
    parent = store.add("original", repo="/some/repo")
    parent.extra = {"session_id": "sess-1", "branch": "overnight/original-abc123",
                    "repo": "/some/repo"}
    store.save(parent)
    child = store.add("go deeper", parent=parent)
    assert child.parent == parent.id
    assert child.repo == "/some/repo"
    assert child.extra["resume_session"] == "sess-1"
    assert child.extra["branch"] == "overnight/original-abc123"


def test_followup_research_job_resumes_session(monkeypatch):
    captured = {}
    def capture(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(
            stdout=json.dumps({"result": "deeper answer", "is_error": False,
                               "session_id": "sess-2"}),
            stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "run", capture)

    parent = store.add("original")
    parent.extra["session_id"] = "sess-1"
    store.save(parent)
    child = runner.run_job(store.add("go deeper", parent=parent), Config())

    assert child.status == store.DONE
    cmd = captured["cmd"]
    assert "--resume" in cmd and "sess-1" in cmd
    assert cmd[cmd.index("-p") + 1] == "go deeper"  # raw prompt, no template
    # new session recorded so the chain can continue
    assert child.extra["session_id"] == "sess-2"


def test_not_before_defers_job(monkeypatch):
    monkeypatch.setattr(limits, "fetch_usage", lambda **kw: limits.Usage(0.0, None, 0.0, None))
    store.add("later", not_before="2026-07-20")
    assert runner.run_batch(Config(), now=NIGHT) == "queue empty"


def test_not_before_runs_on_the_day():
    job = store.add("today", not_before="2026-07-18")
    assert runner.is_due(job, NIGHT)
    assert not runner.is_due(store.add("future", not_before="2026-07-19"), NIGHT)
