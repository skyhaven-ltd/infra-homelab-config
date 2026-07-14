from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    # Naive UTC: SQLite's DateTime column is timezone-unaware, and mixing
    # aware and naive values breaks comparisons.
    return datetime.now(UTC).replace(tzinfo=None)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str] = mapped_column(String(512), default="")
    slug: Mapped[str] = mapped_column(String(256), unique=True)
    current_chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Chapter.index"
    )
    preference: Mapped[BookPreference | None] = relationship(
        back_populates="book", cascade="all, delete-orphan", uselist=False
    )


class BookPreference(Base):
    __tablename__ = "book_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), unique=True)
    mode: Mapped[str] = mapped_column(String(16), default="learn")

    book: Mapped[Book] = relationship(back_populates="preference")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    book: Mapped[Book] = relationship(back_populates="chapters")
    questions: Mapped[list[Question]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )
    companion: Mapped[ChapterCompanion | None] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", uselist=False
    )
    thoughts: Mapped[list[ReadingThought]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )


class ChapterCompanion(Base):
    __tablename__ = "chapter_companions"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), unique=True)
    recap: Mapped[str] = mapped_column(Text, default="")
    prediction: Mapped[str] = mapped_column(Text, default="")
    prediction_reflection: Mapped[str] = mapped_column(Text, default="")
    quiz_question_index: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    chapter: Mapped[Chapter] = relationship(back_populates="companion")


class ReadingThought(Base):
    __tablename__ = "reading_thoughts"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    chapter: Mapped[Chapter] = relationship(back_populates="thoughts")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    type: Mapped[str] = mapped_column(String(32))  # recall|character|plot|theme|...
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text, default="")
    batch_version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    chapter: Mapped[Chapter] = relationship(back_populates="questions")
    attempts: Mapped[list[Attempt]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    review: Mapped[ReviewState | None] = relationship(
        back_populates="question", cascade="all, delete-orphan", uselist=False
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    answer_text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[int] = mapped_column(Integer)  # 1 (guessing) .. 5 (certain)
    correct: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    question: Mapped[Question] = relationship(back_populates="attempts")


class GenerationJob(Base):
    """A queued question-generation request, processed by the host-side
    worker script (subscription seat) instead of a direct API call."""

    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|running|succeeded|failed
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    chapter: Mapped[Chapter] = relationship()


class ReviewState(Base):
    __tablename__ = "review_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), unique=True)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    due_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    question: Mapped[Question] = relationship(back_populates="review")
