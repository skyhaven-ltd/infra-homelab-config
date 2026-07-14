from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Body,
    Depends,
    FastAPI,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_session, init_db
from app.epub import parse_epub
from app.models import Attempt, Book, BookPreference, Chapter, GenerationJob, Question
from app.services import companion as companion_service
from app.services import generation as generation_service
from app.services import jobs as jobs_service
from app.services import scheduler as scheduler_service

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        companion_service.backfill_legacy_progress(db)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="BookBuddy", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _slugify(title: str, db: Session) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "book"
    slug = base
    suffix = 2
    while db.execute(select(Book).where(Book.slug == slug)).scalar_one_or_none():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _get_book(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


def _get_chapter(db: Session, chapter_id: int) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


def _companion_return_path(value: str) -> str:
    return value if re.fullmatch(r"/books/\d+/companion", value) else ""


@app.get("/health")
def health() -> dict[str, str]:
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request, db: Session = Depends(get_session), error: str = ""
) -> HTMLResponse:
    books = db.execute(select(Book).order_by(Book.created_at.desc())).scalars().all()
    due_count = len(scheduler_service.due_questions(db, limit=100))
    return templates.TemplateResponse(
        request,
        "index.html",
        {"books": books, "due_count": due_count, "error": error},
    )


@app.post("/books/upload", response_class=HTMLResponse)
async def upload_book(
    request: Request, file: UploadFile, db: Session = Depends(get_session)
) -> HTMLResponse:
    token = uuid.uuid4().hex
    path = Path(settings.upload_dir) / f"{token}.epub"
    path.write_bytes(await file.read())
    try:
        parsed = parse_epub(str(path))
    except Exception:
        path.unlink(missing_ok=True)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "books": db.execute(select(Book)).scalars().all(),
                "due_count": 0,
                "error": "Could not parse that file as an EPUB.",
            },
            status_code=422,
        )
    return templates.TemplateResponse(
        request,
        "import_confirm.html",
        {"parsed": parsed, "token": token, "mode": "learn"},
    )


@app.post("/books/import")
def import_book(
    request: Request,
    token: str = Form(...),
    mode: str = Form(...),
    chapter_indexes: list[int] | None = Form(None),
    db: Session = Depends(get_session),
) -> Response:
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=400, detail="Invalid upload token")
    path = Path(settings.upload_dir) / f"{token}.epub"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Upload expired or not found")
    parsed = parse_epub(str(path))
    selected_indexes = sorted(set(chapter_indexes or []))
    if not selected_indexes:
        return templates.TemplateResponse(
            request,
            "import_confirm.html",
            {
                "parsed": parsed,
                "token": token,
                "mode": mode,
                "error": "Choose at least one chapter to import.",
            },
            status_code=422,
        )
    if selected_indexes[-1] >= len(parsed.chapters) or selected_indexes[0] < 0:
        raise HTTPException(status_code=400, detail="Invalid chapter selection")
    if mode not in {"learn", "story", "explore"}:
        raise HTTPException(status_code=400, detail="Invalid reading mode")

    book = Book(
        title=parsed.title,
        author=parsed.author,
        slug=_slugify(parsed.title, db),
    )
    db.add(book)
    db.flush()
    db.add(BookPreference(book_id=book.id, mode=mode))
    selected_chapters = [parsed.chapters[index] for index in selected_indexes]
    for index, chapter in enumerate(selected_chapters):
        db.add(
            Chapter(
                book_id=book.id,
                index=index,
                title=chapter.title,
                text=chapter.text,
                word_count=chapter.word_count,
            )
        )
    db.commit()
    companion_service.prepare_chapter(db, book.chapters[0])
    path.unlink(missing_ok=True)
    return RedirectResponse(f"/books/{book.id}", status_code=303)


@app.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(
    request: Request,
    book_id: int,
    db: Session = Depends(get_session),
    error: str = "",
) -> HTMLResponse:
    book = _get_book(db, book_id)
    question_counts = dict(
        db.execute(
            select(Question.chapter_id, func.count(Question.id))
            .join(Chapter, Question.chapter_id == Chapter.id)
            .where(Chapter.book_id == book.id, Question.active)
            .group_by(Question.chapter_id)
        ).all()
    )
    job_status = {
        chapter_id: job.status
        for chapter_id, job in jobs_service.latest_by_chapter(
            db, [c.id for c in book.chapters]
        ).items()
    }
    return templates.TemplateResponse(
        request,
        "book_detail.html",
        {
            "book": book,
            "question_counts": question_counts,
            "job_status": job_status,
            "error": error,
            "notice": request.query_params.get("notice", ""),
        },
    )


@app.get("/books/{book_id}/companion", response_class=HTMLResponse)
def book_companion(
    request: Request, book_id: int, db: Session = Depends(get_session)
) -> HTMLResponse:
    book = _get_book(db, book_id)
    chapter = book.chapters[book.current_chapter_index] if book.chapters else None
    previous_chapter = (
        book.chapters[book.current_chapter_index - 1]
        if chapter and book.current_chapter_index > 0
        else None
    )
    previous_completed = bool(
        previous_chapter and companion_service.is_completed(previous_chapter)
    )
    previous_recap = (
        companion_service.recap_for(previous_chapter) if previous_completed else ""
    )
    previous_prediction = (
        previous_chapter.companion.prediction
        if previous_completed and previous_chapter and previous_chapter.companion
        else ""
    )
    previous_reflection = (
        previous_chapter.companion.prediction_reflection
        if previous_prediction and previous_chapter and previous_chapter.companion
        else ""
    )
    questions_ready = bool(
        chapter and any(question.active for question in chapter.questions)
    )
    latest_job = (
        jobs_service.latest_by_chapter(db, [chapter.id]).get(chapter.id)
        if chapter
        else None
    )
    due_count = len(scheduler_service.due_questions(db, limit=100))
    return templates.TemplateResponse(
        request,
        "companion.html",
        {
            "book": book,
            "chapter": chapter,
            "previous_recap": previous_recap,
            "previous_chapter": previous_chapter if previous_completed else None,
            "previous_prediction": previous_prediction,
            "previous_reflection": previous_reflection,
            "prediction": chapter.companion.prediction
            if chapter and chapter.companion
            else "",
            "thoughts": chapter.thoughts if chapter else [],
            "chapter_completed": companion_service.is_completed(chapter)
            if chapter
            else False,
            "due_count": due_count,
            "questions_ready": questions_ready,
            "preparation_status": latest_job.status if latest_job else "",
        },
    )


@app.post("/chapters/{chapter_id}/prediction")
def save_chapter_prediction(
    chapter_id: int,
    prediction: str = Form(""),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    chapter = _get_chapter(db, chapter_id)
    if chapter.index != chapter.book.current_chapter_index:
        raise HTTPException(status_code=409, detail="Chapter is not current")
    companion_service.save_prediction(db, chapter, prediction)
    return RedirectResponse(f"/books/{chapter.book_id}/companion", status_code=303)


@app.post("/chapters/{chapter_id}/prediction-reflection")
def save_prediction_reflection(
    chapter_id: int,
    reflection: str = Form(..., min_length=1),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    chapter = _get_chapter(db, chapter_id)
    if not companion_service.is_completed(chapter):
        raise HTTPException(status_code=409, detail="Chapter is not complete")
    try:
        companion_service.save_prediction_reflection(db, chapter, reflection)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/books/{chapter.book_id}/companion", status_code=303)


@app.post("/chapters/{chapter_id}/thoughts")
def save_reading_thought(
    chapter_id: int,
    thought: str = Form(..., min_length=1),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    chapter = _get_chapter(db, chapter_id)
    if chapter.index != chapter.book.current_chapter_index:
        raise HTTPException(status_code=409, detail="Chapter is not current")
    try:
        companion_service.save_thought(db, chapter, thought)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/books/{chapter.book_id}/companion", status_code=303)


@app.get("/books/{book_id}/delete", response_class=HTMLResponse)
def confirm_delete_book(
    request: Request, book_id: int, db: Session = Depends(get_session)
) -> HTMLResponse:
    book = _get_book(db, book_id)
    return templates.TemplateResponse(request, "book_delete.html", {"book": book})


@app.post("/books/{book_id}/delete")
def delete_book(
    book_id: int,
    confirmation: str = Form(""),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    book = _get_book(db, book_id)
    if confirmation != "remove":
        raise HTTPException(status_code=400, detail="Book removal was not confirmed")
    chapter_ids = [chapter.id for chapter in book.chapters]
    if chapter_ids:
        db.execute(
            delete(GenerationJob).where(GenerationJob.chapter_id.in_(chapter_ids))
        )
    db.delete(book)
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/books/{book_id}/position")
def set_position(
    book_id: int,
    chapter_index: int = Form(...),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    book = _get_book(db, book_id)
    companion_service.select_chapter(db, book, chapter_index)
    return RedirectResponse(f"/books/{book.id}/companion", status_code=303)


@app.post("/chapters/{chapter_id}/generate")
def generate_chapter_questions(
    chapter_id: int, db: Session = Depends(get_session)
) -> RedirectResponse:
    chapter = _get_chapter(db, chapter_id)
    book = chapter.book

    if not settings.anthropic_api_key:
        # Subscription path: queue the job for the host-side worker instead
        # of paying per-token API costs.
        jobs_service.enqueue(db, chapter)
        return RedirectResponse(
            f"/books/{book.id}?notice=Generation+queued+for+the+worker",
            status_code=303,
        )

    prior_titles = [c.title for c in book.chapters if c.index < chapter.index]
    try:
        material = generation_service.generate_material(
            chapter, prior_titles, book.title
        )
    except generation_service.GenerationError as exc:
        return RedirectResponse(f"/books/{book.id}?error={exc}", status_code=303)
    generation_service.store_material(db, chapter, material)
    return RedirectResponse(f"/chapters/{chapter.id}/quiz", status_code=303)


def _active_questions(db: Session, chapter_id: int) -> list[Question]:
    return list(
        db.execute(
            select(Question)
            .where(Question.chapter_id == chapter_id, Question.active)
            .order_by(Question.id)
        )
        .scalars()
        .all()
    )


@app.get("/chapters/{chapter_id}/quiz", response_class=HTMLResponse)
def chapter_quiz(
    request: Request,
    chapter_id: int,
    question_index: int | None = None,
    db: Session = Depends(get_session),
) -> HTMLResponse:
    chapter = _get_chapter(db, chapter_id)
    questions = _active_questions(db, chapter_id)
    question = None
    if questions:
        if question_index is None:
            question_index = companion_service.quiz_position(chapter, len(questions))
        question_index = max(0, min(question_index, len(questions) - 1))
        question = questions[question_index]
    else:
        question_index = 0
    return templates.TemplateResponse(
        request,
        "quiz.html",
        {
            "chapter": chapter,
            "question": question,
            "question_index": question_index,
            "question_count": len(questions),
            "prediction": chapter.companion.prediction if chapter.companion else "",
        },
    )


@app.post("/chapters/{chapter_id}/quiz", response_class=HTMLResponse)
def chapter_quiz_submit(
    request: Request,
    chapter_id: int,
    question_id: int = Form(...),
    answer_text: str = Form(""),
    confidence: int = Form(3),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    chapter = _get_chapter(db, chapter_id)
    questions = _active_questions(db, chapter_id)
    question = next((item for item in questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    question_index = questions.index(question)
    return templates.TemplateResponse(
        request,
        "quiz_grade.html",
        {
            "chapter": chapter,
            "question": question,
            "answer_text": answer_text,
            "confidence": max(1, min(confidence, 5)),
            "question_index": question_index,
            "question_count": len(questions),
        },
    )


@app.post("/chapters/{chapter_id}/grade")
def chapter_quiz_grade(
    chapter_id: int,
    question_id: int = Form(...),
    answer_text: str = Form(""),
    confidence: int = Form(3),
    correct: str = Form(...),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    chapter = _get_chapter(db, chapter_id)
    questions = _active_questions(db, chapter_id)
    question = next((item for item in questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if correct not in {"yes", "nearly", "no"}:
        raise HTTPException(status_code=400, detail="Invalid grade")
    confidence = max(1, min(confidence, 5))
    was_correct = correct in {"yes", "nearly"}
    if correct == "nearly":
        confidence = min(confidence, 2)
    db.add(
        Attempt(
            question_id=question.id,
            answer_text=answer_text,
            confidence=confidence,
            correct=was_correct,
        )
    )
    scheduler_service.apply_review(db, question, was_correct, confidence)
    db.commit()
    next_index = questions.index(question) + 1
    companion_service.record_quiz_progress(db, chapter, next_index)
    if next_index < len(questions):
        return RedirectResponse(
            f"/chapters/{chapter.id}/quiz",
            status_code=303,
        )
    companion_service.complete_chapter(db, chapter)
    return RedirectResponse(f"/books/{chapter.book_id}/companion", status_code=303)


@app.get("/review", response_class=HTMLResponse)
def review(
    request: Request,
    return_to: str = "",
    db: Session = Depends(get_session),
) -> HTMLResponse:
    due = scheduler_service.due_questions(db)
    return_to = _companion_return_path(return_to)
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "question": due[0] if due else None,
            "due_count": len(due),
            "return_to": return_to,
        },
    )


@app.post("/review/{question_id}", response_class=HTMLResponse)
def review_reveal(
    request: Request,
    question_id: int,
    answer_text: str = Form(""),
    confidence: int = Form(3),
    return_to: str = Form(""),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return templates.TemplateResponse(
        request,
        "review_reveal.html",
        {
            "question": question,
            "answer_text": answer_text,
            "confidence": confidence,
            "return_to": _companion_return_path(return_to),
        },
    )


@app.post("/review/{question_id}/grade")
def review_grade(
    question_id: int,
    answer_text: str = Form(""),
    confidence: int = Form(3),
    correct: str = Form(...),
    return_to: str = Form(""),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if correct not in {"yes", "nearly", "no"}:
        raise HTTPException(status_code=400, detail="Invalid grade")
    was_correct = correct in {"yes", "nearly"}
    if correct == "nearly":
        confidence = min(confidence, 2)
    db.add(
        Attempt(
            question_id=question.id,
            answer_text=answer_text,
            confidence=confidence,
            correct=was_correct,
        )
    )
    scheduler_service.apply_review(db, question, was_correct, confidence)
    db.commit()
    return_to = _companion_return_path(return_to)
    if return_to and not scheduler_service.due_questions(db, limit=1):
        return RedirectResponse(return_to, status_code=303)
    destination = "/review"
    if return_to:
        destination = f"{destination}?return_to={return_to}"
    return RedirectResponse(destination, status_code=303)


def require_worker(authorization: str = Header("")) -> None:
    if not settings.worker_token:
        raise HTTPException(status_code=503, detail="WORKER_TOKEN not configured")
    if authorization != f"Bearer {settings.worker_token}":
        raise HTTPException(status_code=401, detail="Invalid worker token")


def _get_running_job(db: Session, job_id: int) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "running":
        raise HTTPException(status_code=409, detail=f"Job is {job.status}, not running")
    return job


@app.post("/worker/generation-jobs/claim", dependencies=[Depends(require_worker)])
def worker_claim(db: Session = Depends(get_session)) -> dict:
    claimed = jobs_service.claim_next(db)
    if claimed is None:
        return {"job": None}
    job, prompt = claimed
    return {
        "job": {
            "id": job.id,
            "book_title": job.chapter.book.title,
            "chapter_title": job.chapter.title,
            "prompt": prompt,
        }
    }


@app.post(
    "/worker/generation-jobs/{job_id}/complete",
    dependencies=[Depends(require_worker)],
)
def worker_complete(
    job_id: int,
    raw_output: str = Body(..., embed=True),
    db: Session = Depends(get_session),
) -> dict:
    job = _get_running_job(db, job_id)
    try:
        created = jobs_service.complete(db, job, raw_output)
    except generation_service.GenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"questions_created": created}


@app.post(
    "/worker/generation-jobs/{job_id}/fail",
    dependencies=[Depends(require_worker)],
)
def worker_fail(
    job_id: int,
    error: str = Body("", embed=True),
    db: Session = Depends(get_session),
) -> dict:
    job = _get_running_job(db, job_id)
    jobs_service.fail(db, job, error)
    return {"status": "failed"}
