import json
from types import SimpleNamespace

import pytest

from app.models import Book, BookPreference, Chapter, Question
from app.services.generation import (
    GeneratedQuestion,
    GenerationError,
    generate_questions,
    store_questions,
)


class FakeClient:
    def __init__(self, payload: dict | None, stop_reason: str = "end_turn"):
        self._payload = payload
        self._stop_reason = stop_reason
        self.last_kwargs: dict = {}
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        content = []
        if self._payload is not None:
            content = [SimpleNamespace(type="text", text=json.dumps(self._payload))]
        return SimpleNamespace(stop_reason=self._stop_reason, content=content)


def _chapter(db, slug: str) -> Chapter:
    book = Book(title=f"Gen {slug}", slug=f"gen-{slug}")
    db.add(book)
    db.flush()
    chapter = Chapter(
        book_id=book.id, index=1, title="The Second Chapter", text="Once upon..."
    )
    db.add(chapter)
    db.commit()
    return chapter


def test_generate_questions_parses_model_output(db_session):
    chapter = _chapter(db_session, "parse")
    payload = {
        "recap": "X happened, creating a consequence for the next chapter.",
        "questions": [
            {
                "type": "plot",
                "prompt": "Why did X happen?",
                "answer": "Because Y.",
                "source_quote": "Once upon...",
            }
        ],
    }
    fake = FakeClient(payload)
    result = generate_questions(
        chapter, ["The First Chapter"], "Gen parse", client=fake
    )
    assert len(result) == 1
    assert result[0].type == "plot"
    prompt_text = fake.last_kwargs["messages"][0]["content"]
    assert "The First Chapter" in prompt_text
    assert "Once upon..." in prompt_text


def test_generate_questions_raises_on_refusal(db_session):
    chapter = _chapter(db_session, "refusal")
    fake = FakeClient(None, stop_reason="refusal")
    with pytest.raises(GenerationError):
        generate_questions(chapter, [], "Gen refusal", client=fake)


def test_generate_questions_rejects_blank_source_quote(db_session):
    chapter = _chapter(db_session, "blank-source")
    fake = FakeClient(
        {
            "recap": "A recap.",
            "questions": [
                {
                    "type": "plot",
                    "prompt": "What happened?",
                    "answer": "An event.",
                    "source_quote": "   ",
                }
            ],
        }
    )

    with pytest.raises(GenerationError, match="source_quote"):
        generate_questions(chapter, [], "Gen blank source", client=fake)


def test_generate_questions_rejects_unknown_reading_mode(db_session):
    chapter = _chapter(db_session, "unknown-mode")
    db_session.add(BookPreference(book_id=chapter.book_id, mode="mystery"))
    db_session.commit()

    with pytest.raises(GenerationError, match="Unknown reading mode"):
        generate_questions(chapter, [], "Gen unknown mode", client=FakeClient({}))


def test_store_questions_versions_batches(db_session):
    chapter = _chapter(db_session, "version")
    first = [
        GeneratedQuestion(
            type="recall", prompt="P1", answer="A1", source_quote="First passage"
        )
    ]
    second = [
        GeneratedQuestion(
            type="theme", prompt="P2", answer="A2", source_quote="Second passage"
        )
    ]
    store_questions(db_session, chapter, first)
    store_questions(db_session, chapter, second)

    questions = (
        db_session.query(Question).filter(Question.chapter_id == chapter.id).all()
    )
    active = [q for q in questions if q.active]
    assert len(questions) == 2
    assert len(active) == 1
    assert active[0].prompt == "P2"
    assert active[0].batch_version == 2
