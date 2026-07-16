"""SM-2 spaced-repetition scheduling.

Quality (0-5) comes from the reader's three-way self-grade after seeing the
answer. Once a question has been recalled successfully RETIREMENT_RECALLS
times it retires, so the review pool shrinks as books are finished instead of
accumulating into an off-putting backlog.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Question, ReviewState, utcnow

MIN_EASE = 1.3
RETIREMENT_RECALLS = 3
# Retirement pushes due_at past any realistic horizon instead of adding a
# "retired" column: init_db only ever create_alls, so a new column would not
# appear on existing SQLite databases.
RETIREMENT_INTERVAL_DAYS = 36500.0

GRADE_QUALITY = {"yes": 5, "nearly": 3, "no": 1}


def quality_from_grade(grade: str) -> int:
    return GRADE_QUALITY[grade]


def apply_review(db: Session, question: Question, grade: str) -> ReviewState:
    state = db.execute(
        select(ReviewState).where(ReviewState.question_id == question.id)
    ).scalar_one_or_none()
    if state is None:
        # Column defaults only apply at flush, so set initial values here.
        state = ReviewState(
            question_id=question.id,
            repetitions=0,
            interval_days=0.0,
            ease_factor=2.5,
            due_at=utcnow(),
        )
        db.add(state)
        # The session runs with autoflush off; flush so a second review of the
        # same question in this session sees this row instead of duplicating it.
        db.flush()

    quality = quality_from_grade(grade)
    now = utcnow()

    if quality < 3:
        state.repetitions = 0
        state.interval_days = 1.0
    else:
        if state.repetitions == 0:
            state.interval_days = 1.0
        elif state.repetitions == 1:
            state.interval_days = 6.0
        else:
            state.interval_days = round(state.interval_days * state.ease_factor, 1)
        state.repetitions += 1
        if state.repetitions >= RETIREMENT_RECALLS:
            state.interval_days = RETIREMENT_INTERVAL_DAYS

    ease = state.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    state.ease_factor = max(MIN_EASE, round(ease, 2))
    state.last_reviewed_at = now
    state.due_at = now + timedelta(days=state.interval_days)
    return state


def due_questions(db: Session, limit: int = 20) -> list[Question]:
    """Due questions, oldest first; interleaving comes from the ordering
    being by due date rather than by book or chapter."""
    now = utcnow()
    states = (
        db.execute(
            select(ReviewState)
            .join(Question, ReviewState.question_id == Question.id)
            .where(ReviewState.due_at <= now, Question.active)
            .order_by(ReviewState.due_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [state.question for state in states]
