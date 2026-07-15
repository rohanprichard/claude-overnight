from overnight import store


def test_add_and_list_roundtrip():
    job = store.add("what is the capital of france")
    jobs = store.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == job.id
    assert jobs[0].prompt == "what is the capital of france"
    assert jobs[0].status == store.PENDING


def test_list_filters_by_status():
    a = store.add("q1")
    store.add("q2")
    store.mark(a, store.DONE)
    assert len(store.list_jobs(store.PENDING)) == 1
    assert len(store.list_jobs(store.DONE)) == 1


def test_remove():
    job = store.add("bye")
    assert store.remove(job.id) is True
    assert store.remove(job.id) is False
    assert store.list_jobs() == []


def test_mark_running_increments_attempts_and_timestamps():
    job = store.add("q")
    job = store.mark(job, store.RUNNING)
    assert job.attempts == 1
    assert job.started_at is not None
    job = store.mark(job, store.DONE, result_path="/tmp/x.md")
    assert job.finished_at is not None
    reloaded = store.get(job.id)
    assert reloaded.status == store.DONE
    assert reloaded.result_path == "/tmp/x.md"


def test_slug():
    assert store.slug("What is Rust's borrow checker??") == "what-is-rust-s-borrow-checker"
    assert store.slug("   ") == "job"
