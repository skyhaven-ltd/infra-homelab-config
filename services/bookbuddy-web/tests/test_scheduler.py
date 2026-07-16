from datetime import timedelta

from app.models import Book, Chapter, Question, utcnow
from app.services.scheduler import (
    RETIREMENT_INTERVAL_DAYS,
    apply_review,
    due_questions,
    quality_from_grade,
)


def _make_question(db, slug: str) -> Question:
    book = Book(title=f"Sched {slug}", slug=f"sched-{slug}")
    db.add(book)
    db.flush()
    chapter = Chapter(book_id=book.id, index=0, title="C1", text="text")
    db.add(chapter)
    db.flush()
    question = Question(chapter_id=chapter.id, type="recall", prompt="Q?", answer="A")
    db.add(question)
    db.commit()
    return question


def test_quality_mapping_orders_the_three_grades():
    assert quality_from_grade("yes") == 5
    assert quality_from_grade("nearly") == 3
    assert quality_from_grade("no") == 1


def test_intervals_grow_on_success(db_session):
    question = _make_question(db_session, "grow")
    state = apply_review(db_session, question, "yes")
    assert state.interval_days == 1.0
    state = apply_review(db_session, question, "yes")
    assert state.interval_days == 6.0
    db_session.commit()


def test_third_successful_recall_retires_the_question(db_session):
    question = _make_question(db_session, "retire")
    apply_review(db_session, question, "yes")
    apply_review(db_session, question, "yes")
    state = apply_review(db_session, question, "yes")
    db_session.commit()
    assert state.interval_days == RETIREMENT_INTERVAL_DAYS
    assert question.id not in [q.id for q in due_questions(db_session)]


def test_failure_resets_interval(db_session):
    question = _make_question(db_session, "reset")
    apply_review(db_session, question, "yes")
    apply_review(db_session, question, "yes")
    state = apply_review(db_session, question, "no")
    assert state.repetitions == 0
    assert state.interval_days == 1.0
    assert state.ease_factor >= 1.3
    db_session.commit()


def test_due_questions_excludes_future(db_session):
    question = _make_question(db_session, "due")
    state = apply_review(db_session, question, "yes")
    db_session.commit()
    assert question.id not in [q.id for q in due_questions(db_session)]
    state.due_at = utcnow()
    db_session.commit()
    assert question.id in [q.id for q in due_questions(db_session)]


def test_inactive_questions_do_not_displace_active_due_questions(db_session):
    inactive = _make_question(db_session, "inactive-due")
    active = _make_question(db_session, "active-due")
    inactive_state = apply_review(db_session, inactive, "no")
    active_state = apply_review(db_session, active, "no")
    inactive.active = False
    inactive_state.due_at = utcnow() - timedelta(days=2)
    active_state.due_at = utcnow() - timedelta(days=1)
    db_session.commit()

    assert [question.id for question in due_questions(db_session, limit=1)] == [
        active.id
    ]
