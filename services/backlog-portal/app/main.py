from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import jobs, providers
from app.config import Target, get_settings, target_from_id
from app.database import SessionLocal, get_session, init_db
from app.models import AuditEvent, Draft, GenerationJob

settings = get_settings()
security = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.username or not settings.password:
        raise RuntimeError("PORTAL_USERNAME and PORTAL_PASSWORD are required")
    init_db()
    with SessionLocal() as db:
        stranded = (
            db.execute(select(Draft).where(Draft.state == "validation")).scalars().all()
        )
        for draft in stranded:
            target = get_target(draft.target_id)
            draft.item_type = target.item_types[0]
            jobs.enqueue(db, draft)
    yield


app = FastAPI(title="Backlog Portal", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def require_user(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    valid = (
        credentials is not None
        and secrets.compare_digest(
            credentials.username.encode(), settings.username.encode()
        )
        and secrets.compare_digest(
            credentials.password.encode(), settings.password.encode()
        )
    )
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Backlog Portal"'},
        )
    return credentials.username


def require_worker(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {settings.worker_token}"
    if not settings.worker_token or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid worker token")


def get_target(target_id: str) -> Target:
    target = target_from_id(settings, target_id)
    if target is None:
        raise HTTPException(status_code=400, detail="Unknown target")
    return target


def get_draft(db: Session, draft_id: int) -> Draft:
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@app.get("/health")
def health() -> dict[str, str]:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    _: str = Depends(require_user),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    drafts = (
        db.execute(
            select(Draft)
            .where(Draft.state != "deleted")
            .order_by(Draft.created_at.desc())
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(request, "index.html", {"drafts": drafts})


@app.get("/api/destinations/{provider}")
def destinations(provider: str, _: str = Depends(require_user)) -> dict:
    try:
        values = providers.list_destinations(settings, provider)
    except providers.SubmissionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"destinations": values}


@app.post("/drafts")
def create_draft(
    target_id: str = Form(...),
    raw_idea: str = Form(...),
    _: str = Depends(require_user),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    target = get_target(target_id)
    idea = raw_idea.strip()
    if len(idea) < 10 or len(idea) > 20_000:
        raise HTTPException(status_code=422, detail="Idea must be 10-20000 characters")
    draft = Draft(
        target_id=target.id,
        item_type=target.item_types[0],
        raw_idea=idea,
    )
    db.add(draft)
    db.flush()
    jobs.enqueue(db, draft)
    return RedirectResponse(f"/drafts/{draft.id}", status_code=303)


@app.get("/drafts/{draft_id}", response_class=HTMLResponse)
def review_draft(
    request: Request,
    draft_id: int,
    _: str = Depends(require_user),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    draft = get_draft(db, draft_id)
    return templates.TemplateResponse(
        request,
        "review.html",
        {"draft": draft, "target": get_target(draft.target_id)},
    )


@app.post("/drafts/{draft_id}/submit")
def submit_draft(
    request: Request,
    draft_id: int,
    title: str = Form(...),
    item_type: str = Form(...),
    description: str = Form(...),
    acceptance_criteria: str = Form(""),
    priority: str = Form(""),
    area: str = Form(""),
    iteration: str = Form(""),
    labels: str = Form(""),
    assignee: str = Form(""),
    _: str = Depends(require_user),
    db: Session = Depends(get_session),
) -> Response:
    draft = get_draft(db, draft_id)
    if draft.state not in {"review", "failed"}:
        raise HTTPException(status_code=409, detail="Draft is not ready for submission")
    target = get_target(draft.target_id)
    supported_types = {value.casefold(): value for value in target.item_types}
    selected_type = supported_types.get(item_type.strip().casefold())
    if selected_type is None:
        raise HTTPException(status_code=422, detail="Unsupported item type")
    draft.item_type = selected_type
    draft.title = title.strip()[:512]
    draft.description = description.strip()
    draft.acceptance_criteria = acceptance_criteria.strip()
    draft.priority = priority.strip()[:32]
    draft.area = area.strip()[:256]
    draft.iteration = iteration.strip()[:256]
    draft.labels = labels.strip()[:1024]
    draft.assignee = assignee.strip()[:256]
    if not draft.title or not draft.description:
        raise HTTPException(
            status_code=422, detail="Title and description are required"
        )
    draft.state = "submitting"
    db.commit()
    try:
        result = providers.submit(settings, target, draft)
    except providers.SubmissionError as exc:
        draft.state = "review"
        db.add(
            AuditEvent(
                draft_id=draft.id,
                action="provider.failed",
                detail=str(exc)[:512],
            )
        )
        db.commit()
        return templates.TemplateResponse(
            request,
            "review.html",
            {"draft": draft, "target": target, "error": str(exc)},
            status_code=502,
        )
    draft.state = "submitted"
    draft.remote_url = result.url
    draft.remote_external_id = result.external_id
    draft.remote_project_item_id = result.project_item_id
    db.add(
        AuditEvent(
            draft_id=draft.id,
            action="provider.submitted",
            detail=f"external_id={result.external_id}",
        )
    )
    db.commit()
    return RedirectResponse(f"/drafts/{draft.id}", status_code=303)


@app.post("/drafts/{draft_id}/delete")
def delete_draft(
    request: Request,
    draft_id: int,
    _: str = Depends(require_user),
    db: Session = Depends(get_session),
) -> Response:
    draft = get_draft(db, draft_id)
    if draft.state == "deleted":
        return RedirectResponse("/", status_code=303)
    target = get_target(draft.target_id)
    try:
        providers.close(settings, target, draft)
    except providers.SubmissionError:
        draft.state = "sync-failed"
        db.add(AuditEvent(draft_id=draft.id, action="provider.delete_failed"))
        db.commit()
        return templates.TemplateResponse(
            request,
            "review.html",
            {
                "draft": draft,
                "target": target,
                "error": "The remote item could not be updated. Retry the removal.",
            },
            status_code=502,
        )
    draft.state = "deleted"
    db.add(AuditEvent(draft_id=draft.id, action="provider.deleted"))
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/worker/reconcile", dependencies=[Depends(require_worker)])
def reconcile_drafts(db: Session = Depends(get_session)) -> dict[str, int]:
    reconciled = 0
    drafts = db.execute(select(Draft).where(Draft.state == "submitted")).scalars()
    for draft in drafts:
        try:
            closed = providers.is_closed(settings, get_target(draft.target_id), draft)
        except providers.SubmissionError:
            db.add(AuditEvent(draft_id=draft.id, action="provider.reconcile_failed"))
            continue
        if closed:
            draft.state = "resolved"
            db.add(AuditEvent(draft_id=draft.id, action="provider.resolved"))
            reconciled += 1
    db.commit()
    return {"reconciled": reconciled}


@app.post("/worker/jobs/claim", dependencies=[Depends(require_worker)])
def claim_job(db: Session = Depends(get_session)) -> dict:
    return {
        "job": jobs.claim_next(
            db,
            lambda draft: get_target(draft.target_id),
            lambda target: providers.load_template_bodies(settings, target),
        )
    }


@app.post("/drafts/{draft_id}/refine")
def refine_draft(
    draft_id: int,
    _: str = Depends(require_user),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    draft = get_draft(db, draft_id)
    if draft.state not in {"review", "failed"}:
        raise HTTPException(status_code=409, detail="Draft cannot be refined again")
    draft.title = ""
    draft.description = ""
    draft.acceptance_criteria = ""
    draft.state = "queued"
    jobs.enqueue(db, draft)
    return RedirectResponse(f"/drafts/{draft.id}", status_code=303)


@app.post("/worker/jobs/{job_id}/complete", dependencies=[Depends(require_worker)])
def complete_job(
    job_id: int,
    payload: dict,
    db: Session = Depends(get_session),
) -> dict[str, str]:
    job = db.get(GenerationJob, job_id)
    if job is None or job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running")
    try:
        jobs.complete(
            db,
            job,
            str(payload.get("raw_output", "")),
            (target := get_target(job.draft.target_id)),
            providers.load_template_bodies(settings, target),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "succeeded"}


@app.post("/worker/jobs/{job_id}/fail", dependencies=[Depends(require_worker)])
def fail_job(
    job_id: int,
    payload: dict,
    db: Session = Depends(get_session),
) -> dict[str, str]:
    job = db.get(GenerationJob, job_id)
    if job is None or job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running")
    jobs.fail(db, job, str(payload.get("error", "Worker failed")))
    return {"status": "failed"}
