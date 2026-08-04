from __future__ import annotations

import json
import re
from collections.abc import Callable

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


def claim_next(
    db: Session,
    resolve_target: Callable[[Draft], Target],
    load_templates: Callable[[Target], dict[str, str]],
) -> dict | None:
    job = db.execute(
        select(GenerationJob)
        .where(GenerationJob.status == "pending")
        .order_by(GenerationJob.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    target = resolve_target(job.draft)
    try:
        template_bodies = load_templates(target)
    except RuntimeError as exc:
        fail(db, job, f"Canonical template loading failed: {exc}")
        return None
    job.status = "running"
    job.draft.state = "refining"
    db.add(AuditEvent(draft_id=job.draft.id, action="ai.claimed"))
    db.commit()
    prompt = f"""Turn this rough backlog idea into a concise, implementation-ready item.
Destination: {target.provider} / {target.organisation} / {target.container}
Choose exactly one item type from: {", ".join(target.item_types)}
Template instructions: {target.template}
Canonical template mappings: {json.dumps(target.template_mappings, sort_keys=True)}
Rough idea:
{job.draft.raw_idea}

Return JSON matching the supplied schema. Set item_type first, then set description to
one completed copy of that type's canonical Markdown template body. Preserve its
headings, replace every instruction and placeholder with the refined content, and do
not add duplicate Item type or Acceptance criteria sections. Acceptance criteria must
also be returned as individually testable items in the acceptance_criteria array.
Do not invent credentials, people, deadlines, or business facts. Use an empty string
or empty list when metadata cannot be inferred.

Canonical template bodies by item type:
{json.dumps(template_bodies, indent=2, sort_keys=True)}
"""
    return {"id": job.id, "draft_id": job.draft.id, "prompt": prompt}


def _template_markers(body: str) -> list[str]:
    return [
        line.strip()
        for line in body.splitlines()
        if re.fullmatch(r"#{1,6}\s+.+|\*\*.+\*\*", line.strip())
    ]


def render_completed_template(template_body: str, generated_body: str) -> str:
    canonical = _template_markers(template_body)
    generated = _template_markers(generated_body)
    if not canonical or generated == canonical:
        return generated_body.strip()

    title = canonical[0] if canonical[0].startswith("# ") else ""
    sections = canonical[1:] if title else canonical
    content: list[str] = []
    buffer: list[str] = []
    for line in generated_body.splitlines():
        if re.fullmatch(r"#{1,6}\s+.+|\*\*.+\*\*", line.strip()):
            if any(value.strip() for value in buffer):
                content.append("\n".join(buffer).strip())
            buffer = []
        else:
            buffer.append(line)
    if any(value.strip() for value in buffer):
        content.append("\n".join(buffer).strip())
    if len(content) != len(sections):
        return generated_body.strip()

    parts = [title] if title else []
    for marker, value in zip(sections, content, strict=True):
        parts.extend([marker, value])
    return "\n\n".join(parts)


def complete(
    db: Session,
    job: GenerationJob,
    raw_output: str,
    target: Target,
    template_bodies: dict[str, str],
) -> None:
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
    supported_types = {item.casefold(): item for item in target.item_types}
    requested_type = str(value.get("item_type", "")).strip()
    draft.item_type = supported_types.get(requested_type.casefold(), draft.item_type)
    draft.title = title[:512]
    draft.description = render_completed_template(
        template_bodies[draft.item_type], description
    )
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
    source = "ai" if requested_type.casefold() in supported_types else "fallback"
    db.add(
        AuditEvent(
            draft_id=draft.id,
            action="classification.completed",
            detail=f"type={draft.item_type}; source={source}",
        )
    )
    db.add(AuditEvent(draft_id=draft.id, action="ai.completed"))
    db.commit()


def fail(db: Session, job: GenerationJob, error: str) -> None:
    job.status = "failed"
    job.error = error[:2000]
    job.draft.state = "failed"
    db.add(AuditEvent(draft_id=job.draft.id, action="ai.failed", detail=error[:512]))
    db.commit()
