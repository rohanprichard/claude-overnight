import subprocess

import pytest

from overnight import runner, store, trust
from overnight.config import Config


@pytest.fixture(autouse=True)
def claude_on_path(monkeypatch):
    monkeypatch.setattr(runner, "claude_path", lambda: "/fake/bin/claude")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "project"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def fake_invoke(edit=None, error=None):
    """Mock _invoke_claude; optionally writes a file into the worktree cwd."""
    def invoke(cmd, cwd, timeout_minutes):
        if edit:
            (cwd / edit).write_text("made overnight\n")
        return ("did the thing", error)
    return invoke


def test_untrusted_repo_fails_without_running(repo, monkeypatch):
    called = []
    monkeypatch.setattr(runner, "_invoke_claude", lambda *a, **k: called.append(1))
    job = runner.run_job(store.add("add feature", repo=str(repo)), Config())
    assert job.status == store.FAILED
    assert "not trusted" in job.error
    assert not called


def test_non_git_dir_fails(tmp_path):
    job = runner.run_job(store.add("x", repo=str(tmp_path)), Config())
    assert job.status == store.FAILED
    assert "not a git repo" in job.error


def test_trusted_repo_job_lands_on_branch(repo, monkeypatch):
    trust.trust(str(repo))
    monkeypatch.setattr(runner, "_invoke_claude", fake_invoke(edit="feature.py"))
    job = runner.run_job(store.add("add feature", repo=str(repo)), Config())

    assert job.status == store.DONE
    branch = job.extra["branch"]
    assert branch.startswith("overnight/")
    # branch exists and contains the change; main untouched
    files = subprocess.run(["git", "ls-tree", "--name-only", branch],
                           cwd=repo, capture_output=True, text=True).stdout
    assert "feature.py" in files
    main_files = subprocess.run(["git", "ls-tree", "--name-only", "main"],
                                cwd=repo, capture_output=True, text=True).stdout
    assert "feature.py" not in main_files
    # worktree cleaned up
    worktrees = subprocess.run(["git", "worktree", "list"],
                               cwd=repo, capture_output=True, text=True).stdout
    assert str(job.id) not in worktrees
    # report references the branch
    assert branch in open(job.result_path).read()


def test_failed_job_with_changes_keeps_wip_branch(repo, monkeypatch):
    trust.trust(str(repo))
    monkeypatch.setattr(runner, "_invoke_claude",
                        fake_invoke(edit="half.py", error="tests exploded"))
    job = runner.run_job(store.add("hard task", repo=str(repo)), Config())
    assert job.status == store.FAILED
    branch = job.extra["branch"]
    log = subprocess.run(["git", "log", "-1", "--format=%s", branch],
                         cwd=repo, capture_output=True, text=True).stdout
    assert log.startswith("WIP overnight")


def test_failed_job_without_changes_drops_branch(repo, monkeypatch):
    trust.trust(str(repo))
    monkeypatch.setattr(runner, "_invoke_claude", fake_invoke(error="crashed early"))
    job = runner.run_job(store.add("task", repo=str(repo)), Config())
    assert job.status == store.FAILED
    branches = subprocess.run(["git", "branch", "--list", "overnight/*"],
                              cwd=repo, capture_output=True, text=True).stdout
    assert branches.strip() == ""


def test_limit_error_requeues_and_drops_branch(repo, monkeypatch):
    trust.trust(str(repo))
    monkeypatch.setattr(runner, "_invoke_claude", fake_invoke(error="usage limit reached"))
    job = runner.run_job(store.add("task", repo=str(repo)), Config())
    assert job.status == store.PENDING


def test_trust_roundtrip(tmp_path):
    repo = str(tmp_path / "r")
    assert not trust.is_trusted(repo)
    trust.trust(repo)
    assert trust.is_trusted(repo)
    assert trust.untrust(repo)
    assert not trust.is_trusted(repo)


def test_first_flag_orders_queue():
    store.add("later")
    store.add("urgent", first=True)
    jobs = store.list_jobs(store.PENDING)
    assert jobs[0].prompt == "urgent"
