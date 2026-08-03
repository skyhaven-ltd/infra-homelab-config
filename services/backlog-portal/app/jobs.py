from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Target
from app.models import AuditEvent, Draft, GenerationJob


def enqueue(db: Session, draft: Draft) -> GenerationJob:
    job = GenerationJob(draft_id=draft.id, status="pending")
    db.add(job)
    db.add(AuditEvent(draft_id=draft.id, action="draft.queued"))
    db.commit()
    return job


def claim_next(db: Session, targets: tuple[Target, ...]) -> dict | None:
    job = db.execute(
        select(GenerationJob)
        .where(GenerationJob.status == "pending")
        .order_by(GenerationJob.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    target = next(value for value in targets if value.id == job.draft.target_id)
    template_mapping = target.template_mappings[job.draft.item_type]
    job.status = "running"
    job.draft.state = "refining"
    db.add(AuditEvent(draft_id=job.draft.id, action="ai.claimed"))
    db.commit()
    prompt = f"""Turn this rough backlog idea into a concise, implementation-ready item.
Destination: {target.provider} / {target.organisation} / {target.container}
Item type: {job.draft.item_type}
Template instructions: {target.template}
Canonical template mapping: {template_mapping}
Rough idea:
{job.draft.raw_idea}

Do not invent credentials, people, deadlines, or business facts. Return JSON matching
the supplied schema. Acceptance criteria must be individually testable. Use an empty
string or empty list when metadata cannot be inferred.
"""
    return {"id": job.id, "draft_id": job.draft.id, "prompt": prompt}


def complete(db: Session, job: GenerationJob, raw_output: str) -> None:
    try:
        value = json.loads(raw_output)
        title = str(value["title"]).strip()
        description = str(value["description"]).strip()
        criteria = value["acceptance_criteria"]
        if not title or not description or not isinstance(criteria, list):
            raise ValueError("title, description, and acceptance_criteria are required")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        fail(db, job, f"Invalid worker output: {exc}")
        raise ValueError(f"Invalid worker output: {exc}") from exc

    draft = job.draft
    draft.title = title[:512]
    draft.description = description
    draft.acceptance_criteria = "\n".join(
        f"- [ ] {str(item).strip()}" for item in criteria if str(item).strip()
    )
    draft.priority = str(value.get("priority", ""))[:32]
    draft.area = str(value.get("area", ""))[:256]
    draft.iteration = str(value.get("iteration", ""))[:256]
    labels = value.get("labels", [])
    draft.labels = ", ".join(str(item).strip() for item in labels if str(item).strip())
    draft.assignee = str(value.get("assignee", ""))[:256]
    draft.state = "review"
    job.status = "succeeded"
    job.error = ""
    db.add(AuditEvent(draft_id=draft.id, action="ai.completed"))
    db.commit()


def fail(db: Session, job: GenerationJob, error: str) -> None:
    job.status = "failed"
    job.error = error[:2000]
    job.draft.state = "failed"
    db.add(AuditEvent(draft_id=job.draft.id, action="ai.failed", detail=error[:512]))
    db.commit()
