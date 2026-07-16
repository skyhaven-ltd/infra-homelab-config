"""Reading-companion lifecycle operations.

Routes tell this module what the reader did; it owns the follow-on work that
BookBuddy should perform without asking the reader to administer the app.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Book,
    BookPreference,
    Chapter,
    ChapterCompanion,
    GenerationJob,
    utcnow,
)
from app.services import jobs


def _state_for(db: Session, chapter: Chapter) -> ChapterCompanion:
    companion = chapter.companion
    if companion is None:
        companion = ChapterCompanion(chapter_id=chapter.id)
        chapter.companion = companion
        db.add(companion)
        db.flush()
    return companion


def prepare_chapter(db: Session, chapter: Chapter) -> GenerationJob | None:
    """Ensure a chapter's questions are being prepared exactly once."""
    if any(question.active for question in chapter.questions):
        return None
    return jobs.enqueue(db, chapter)


def recap_for(chapter: Chapter) -> str:
    """Return the generated recap, or a spoiler-safe fallback for old imports."""
    if chapter.companion and chapter.companion.recap:
        return chapter.companion.recap
    remembered_answers = [
        question.answer.strip()
        for question in chapter.questions
        if question.active
        and question.type not in {"prediction", "elaboration"}
        and question.answer.strip()
    ]
    return " ".join(remembered_answers[:4])


def select_chapter(db: Session, book: Book, chapter_index: int) -> Chapter | None:
    """Move the companion to a chapter and prepare it in the background."""
    if not book.chapters:
        return None
    selected_index = max(0, min(chapter_index, len(book.chapters) - 1))
    book.current_chapter_index = selected_index
    db.commit()
    chapter = book.chapters[selected_index]
    prepare_chapter(db, chapter)
    return chapter


def complete_chapter(db: Session, chapter: Chapter) -> Chapter | None:
    """Advance after the current chapter and prepare what comes next."""
    book = chapter.book
    if chapter.index != book.current_chapter_index:
        return None
    companion = _state_for(db, chapter)
    companion.completed_at = utcnow()
    db.commit()
    next_index = chapter.index + 1
    if next_index >= len(book.chapters):
        return None
    return select_chapter(db, book, next_index)


def quiz_position(chapter: Chapter, question_count: int) -> int:
    """Return the next unanswered position for an interrupted chapter quiz."""
    position = chapter.companion.quiz_question_index if chapter.companion else 0
    return max(0, min(position, max(question_count - 1, 0)))


def record_quiz_progress(db: Session, chapter: Chapter, next_index: int) -> None:
    companion = _state_for(db, chapter)
    companion.quiz_question_index = next_index
    db.commit()


def is_completed(chapter: Chapter) -> bool:
    return bool(chapter.companion and chapter.companion.completed_at)


def backfill_legacy_progress(db: Session) -> None:
    """Translate pre-companion reading positions into explicit completion state."""
    legacy_books = (
        db.execute(
            select(Book)
            .outerjoin(BookPreference, BookPreference.book_id == Book.id)
            .where(BookPreference.id.is_(None))
        )
        .scalars()
        .all()
    )
    if not legacy_books:
        return
    now = utcnow()
    for book in legacy_books:
        db.add(BookPreference(book_id=book.id, mode="learn"))
        for chapter in book.chapters:
            if chapter.index < book.current_chapter_index:
                _state_for(db, chapter).completed_at = now
    db.commit()
