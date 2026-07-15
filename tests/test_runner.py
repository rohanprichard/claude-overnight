import json
import subprocess

import pytest
from datetime import datetime, time
from types import SimpleNamespace

from overnight import limits, paths, runner, store
from overnight.config import Config

NIGHT = datetime(2026, 7, 16, 3, 0)
DAY = datetime(2026, 7, 16, 14, 0)


def cfg(**kw) -> Config:
    return Config(**kw)


def usage(five=0.0, seven=0.0) -> limits.Usage:
    return limits.Usage(five_hour_pct=five, seven_day_pct=seven)


class TestShouldStart:
    def test_runs_when_clear(self):
        assert runner.should_start(cfg(), usage(5, 30), NIGHT).run

    def test_blocked_outside_window(self):
        d = runner.should_start(cfg(), usage(0, 0), DAY)
        assert not d.run and "window" in d.reason

    def test_force_overrides_window(self):
        assert runner.should_start(cfg(), usage(99, 99), DAY, force=True).run

    def test_blocked_by_five_hour_start_cap(self):
        d = runner.should_start(cfg(start_max_utilization=20), usage(five=35), NIGHT)
        assert not d.run and "5h" in d.reason

    def test_blocked_by_weekly_cap(self):
        d = runner.should_start(cfg(weekly_max_utilization=80), usage(seven=91), NIGHT)
        assert not d.run and "weekly" in d.reason

    def test_unknown_usage_is_optimistic(self):
        d = runner.should_start(cfg(), None, NIGHT)
        assert d.run and "optimistic" in d.reason


class TestShouldContinue:
    def test_stops_at_stop_threshold(self):
        d = runner.should_continue(cfg(stop_utilization=60), usage(five=60), NIGHT)
        assert not d.run

    def test_continues_below_threshold(self):
        assert runner.should_continue(cfg(), usage(five=40), NIGHT).run

    def test_stops_when_window_ends(self):
        assert not runner.should_continue(cfg(), usage(), DAY).run


@pytest.fixture(autouse=True)
def claude_on_path(monkeypatch):
    monkeypatch.setattr(runner, "claude_path", lambda: "/fake/bin/claude")


def fake_claude(result: str, is_error: bool = False, returncode: int = 0):
    payload = json.dumps({"result": result, "is_error": is_error})
    def run(cmd, **kwargs):
        return SimpleNamespace(stdout=payload, stderr="", returncode=returncode)
    return run


class TestRunJob:
    def test_success_writes_markdown_result(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_claude("Paris is the capital."))
        job = store.add("capital of france?")
        job = runner.run_job(job, cfg())
        assert job.status == store.DONE
        content = open(job.result_path).read()
        assert "Paris is the capital." in content
        assert "capital of france?" in content

    def test_error_marks_failed(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_claude("something broke", is_error=True))
        job = runner.run_job(store.add("q"), cfg())
        assert job.status == store.FAILED
        assert "something broke" in job.error

    def test_limit_error_requeues_job(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_claude("5-hour usage limit reached", is_error=True))
        job = runner.run_job(store.add("q"), cfg())
        assert job.status == store.PENDING
        assert "hit limit" in job.error

    def test_timeout_marks_failed(self, monkeypatch):
        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 1)
        monkeypatch.setattr(subprocess, "run", boom)
        job = runner.run_job(store.add("q"), cfg(job_timeout_minutes=1))
        assert job.status == store.FAILED
        assert "timed out" in job.error

    def test_missing_cli_marks_failed(self, monkeypatch):
        monkeypatch.setattr(runner, "claude_path", lambda: None)
        job = runner.run_job(store.add("q"), cfg())
        assert job.status == store.FAILED
        assert "not found" in job.error
        assert job.attempts == 0  # never started, retryable after fix


class TestRunBatch:
    def test_empty_queue(self):
        assert runner.run_batch(cfg()) == "queue empty"

    def test_runs_all_jobs_and_updates_index(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_claude("answer"))
        monkeypatch.setattr(limits, "fetch_usage", lambda **kw: usage(5, 10))
        monkeypatch.setattr(runner.notify, "send", lambda *a: None)
        store.add("q1")
        store.add("q2")
        summary = runner.run_batch(cfg(), now=NIGHT)
        assert summary.startswith("2 done, 0 failed")
        index = (paths.results_dir() / "index.md").read_text()
        assert "q1" in index and "q2" in index

    def test_respects_start_decision(self, monkeypatch):
        monkeypatch.setattr(limits, "fetch_usage", lambda **kw: usage(five=90))
        store.add("q1")
        result = runner.run_batch(cfg(), now=NIGHT)
        assert result.startswith("not running")
        assert store.list_jobs(store.PENDING)

    def test_stops_after_limit_hit_mid_batch(self, monkeypatch):
        calls = []
        def limited(cmd, **kwargs):
            calls.append(1)
            return SimpleNamespace(
                stdout=json.dumps({"result": "usage limit reached", "is_error": True}),
                stderr="", returncode=1)
        monkeypatch.setattr(subprocess, "run", limited)
        monkeypatch.setattr(limits, "fetch_usage", lambda **kw: usage(0, 0))
        monkeypatch.setattr(runner.notify, "send", lambda *a: None)
        store.add("q1")
        store.add("q2")
        runner.run_batch(cfg(), now=NIGHT)
        assert len(calls) == 1  # second job never ran
        assert len(store.list_jobs(store.PENDING)) == 2  # both still queued

    def test_lock_prevents_concurrent_runs(self, monkeypatch):
        store.add("q1")
        paths.ensure_dirs()
        paths.lock_path().write_text("123")
        assert runner.run_batch(cfg(), now=NIGHT) == "another runner is active"

    def test_skips_jobs_out_of_attempts(self, monkeypatch):
        job = store.add("q1")
        job.attempts = 2
        store.save(job)
        assert runner.run_batch(cfg(max_attempts=2), now=NIGHT) == "queue empty"
