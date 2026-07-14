"""Generation job queue.

When no ANTHROPIC_API_KEY is configured, question generation is queued as a
GenerationJob instead of calling the API. A host-side worker (see
scripts/process_generation_jobs.py) claims jobs over HTTP, runs the prompt
through a subscription-billed CLI (codex exec), and posts the JSON back —
so generation rides an existing subscription instead of per-token API costs.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chapter, GenerationJob
from app.services import generation


def enqueue(db: Session, chapter: Chapter) -> GenerationJob:
    existing = db.execute(
        select(GenerationJob).where(
            GenerationJob.chapter_id == chapter.id,
            GenerationJob.status.in_(["pending", "running"]),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    job = GenerationJob(chapter_id=chapter.id, status="pending")
    db.add(job)
    db.commit()
    return job


def claim_next(db: Session) -> tuple[GenerationJob, str] | None:
    """Claim the oldest pending job and return it with its built prompt."""
    job = db.execute(
        select(GenerationJob)
        .where(GenerationJob.status == "pending")
        .order_by(GenerationJob.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    chapter = job.chapter
    book = chapter.book
    prior_titles = [c.title for c in book.chapters if c.index < chapter.index]
    prompt = generation.build_worker_prompt(book.title, chapter, prior_titles)
    job.status = "running"
    db.commit()
    return job, prompt


def complete(db: Session, job: GenerationJob, raw_output: str) -> int:
    try:
        material = generation.parse_raw_output(raw_output)
    except generation.GenerationError as exc:
        job.status = "failed"
        job.error = str(exc)
        db.commit()
        raise
    generation.store_material(db, job.chapter, material)
    job.status = "succeeded"
    job.error = ""
    db.commit()
    return len(material.questions)


def fail(db: Session, job: GenerationJob, error: str) -> None:
    job.status = "failed"
    job.error = error[:2000]
    db.commit()


def latest_by_chapter(db: Session, chapter_ids: list[int]) -> dict[int, GenerationJob]:
    if not chapter_ids:
        return {}
    jobs = (
        db.execute(
            select(GenerationJob)
            .where(GenerationJob.chapter_id.in_(chapter_ids))
            .order_by(GenerationJob.created_at.desc())
        )
        .scalars()
        .all()
    )
    latest: dict[int, GenerationJob] = {}
    for job in jobs:
        latest.setdefault(job.chapter_id, job)
    return latest
