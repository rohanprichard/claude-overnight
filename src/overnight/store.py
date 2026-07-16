"""Job store: one JSON file per job under ~/.overnight/queue/."""

import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import paths

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class Job:
    id: str
    prompt: str
    created_at: str
    status: str = PENDING
    attempts: int = 0
    error: str | None = None
    result_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    repo: str | None = None
    model: str | None = None
    priority: int = 0
    extra: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "job"


def _job_path(job_id: str):
    return paths.queue_dir() / f"{job_id}.json"


def save(job: Job) -> None:
    paths.ensure_dirs()
    _job_path(job.id).write_text(json.dumps(asdict(job), indent=2))


def add(prompt: str, repo: str | None = None, model: str | None = None,
        first: bool = False) -> Job:
    job_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)
    job = Job(id=job_id, prompt=prompt.strip(), created_at=_now_iso(),
              repo=repo, model=model, priority=1 if first else 0)
    save(job)
    return job


def get(job_id: str) -> Job | None:
    path = _job_path(job_id)
    if not path.exists():
        return None
    return Job(**json.loads(path.read_text()))


def remove(job_id: str) -> bool:
    path = _job_path(job_id)
    if path.exists():
        path.unlink()
        return True
    return False


def list_jobs(status: str | None = None) -> list[Job]:
    paths.ensure_dirs()
    jobs = []
    for f in sorted(paths.queue_dir().glob("*.json")):
        try:
            jobs.append(Job(**json.loads(f.read_text())))
        except (json.JSONDecodeError, TypeError):
            continue
    if status:
        jobs = [j for j in jobs if j.status == status]
    jobs.sort(key=lambda j: (-j.priority, j.id))
    return jobs


def mark(job: Job, status: str, **fields) -> Job:
    job.status = status
    for k, v in fields.items():
        setattr(job, k, v)
    if status == RUNNING:
        job.started_at = _now_iso()
        job.attempts += 1
    if status in (DONE, FAILED, SKIPPED):
        job.finished_at = _now_iso()
    save(job)
    return job
