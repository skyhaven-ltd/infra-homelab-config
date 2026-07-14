from datetime import timedelta

from app.models import Book, Chapter, Question, utcnow
from app.services.scheduler import apply_review, due_questions, quality_from


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


def test_quality_mapping_punishes_confident_mistakes():
    assert quality_from(True, 5) == 5
    assert quality_from(True, 1) == 3
    assert quality_from(False, 5) == 0
    assert quality_from(False, 1) == 2


def test_intervals_grow_on_success(db_session):
    question = _make_question(db_session, "grow")
    state = apply_review(db_session, question, correct=True, confidence=4)
    assert state.interval_days == 1.0
    state = apply_review(db_session, question, correct=True, confidence=4)
    assert state.interval_days == 6.0
    state = apply_review(db_session, question, correct=True, confidence=4)
    assert state.interval_days > 6.0
    db_session.commit()


def test_failure_resets_interval(db_session):
    question = _make_question(db_session, "reset")
    apply_review(db_session, question, correct=True, confidence=4)
    apply_review(db_session, question, correct=True, confidence=4)
    state = apply_review(db_session, question, correct=False, confidence=5)
    assert state.repetitions == 0
    assert state.interval_days == 1.0
    assert state.ease_factor >= 1.3
    db_session.commit()


def test_due_questions_excludes_future(db_session):
    question = _make_question(db_session, "due")
    state = apply_review(db_session, question, correct=True, confidence=4)
    db_session.commit()
    assert question.id not in [q.id for q in due_questions(db_session)]
    state.due_at = utcnow()
    db_session.commit()
    assert question.id in [q.id for q in due_questions(db_session)]


def test_inactive_questions_do_not_displace_active_due_questions(db_session):
    inactive = _make_question(db_session, "inactive-due")
    active = _make_question(db_session, "active-due")
    inactive_state = apply_review(db_session, inactive, correct=False, confidence=3)
    active_state = apply_review(db_session, active, correct=False, confidence=3)
    inactive.active = False
    inactive_state.due_at = utcnow() - timedelta(days=2)
    active_state.due_at = utcnow() - timedelta(days=1)
    db_session.commit()

    assert [question.id for question in due_questions(db_session, limit=1)] == [
        active.id
    ]
