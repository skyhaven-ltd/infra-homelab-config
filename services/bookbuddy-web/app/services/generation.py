"""Chapter-scoped question generation via the Claude API.

The model only ever sees the current chapter's text plus the titles of
chapters that come before it — never later chapters — which prevents both
spoiler questions and cross-chapter confusion. Every question carries a
supporting quote so answers stay verifiable against the text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chapter, ChapterCompanion, Question

QUESTION_TYPES = [
    "recall",
    "character",
    "plot",
    "theme",
    "elaboration",
]

MODE_GUIDANCE = {
    "learn": "Prioritise concepts, contrasts, examples, and practical application.",
    "story": (
        "Prioritise character motivations and unresolved threads, plot causality, "
        "and the rules of the world."
    ),
    "explore": (
        "Prioritise themes, striking ideas, reflection, and connections to the "
        "reader's own experience."
    ),
}

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "recap": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": QUESTION_TYPES},
                    "prompt": {"type": "string"},
                    "answer": {"type": "string"},
                    "source_quote": {"type": "string"},
                },
                "required": ["type", "prompt", "answer", "source_quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["recap", "questions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You write retrieval-practice questions for one chapter of a book, applying the
principles of 'Make It Stick'. The reader answers from memory after finishing
the chapter, so questions must be answerable from this chapter alone.

Rules:
- Base every question ONLY on the chapter text provided. You are given the
  titles of earlier chapters as context, but you have not seen later chapters
  and must not speculate about them.
- For fiction, cover character motivation ('character'), plot causality
  ('plot'), and theme or world-building rules ('theme') — not just factual
  recall ('recall').
- Include one 'elaboration' question connecting the material to earlier
  chapters or the reader's own knowledge.
- The reader's time is precious: ask only about the chapter's most
  consequential material, never padding to reach a count.
- Every question needs a short verbatim supporting quote from the chapter in
  'source_quote' (for 'elaboration', quote the passage that motivates the
  question).
- Write clear, specific prompts a reader can answer in one to three sentences.
- Also write 'recap': a warm, concise "Previously on" summary of this chapter
  for the reader to see before starting the following chapter. Include the
  argument or events that matter going forward, but nothing beyond this text.
"""


class GenerationError(RuntimeError):
    pass


@dataclass
class GeneratedQuestion:
    type: str
    prompt: str
    answer: str
    source_quote: str


@dataclass
class GeneratedMaterial:
    recap: str
    questions: list[GeneratedQuestion]


def _build_user_prompt(
    book_title: str, chapter: Chapter, prior_titles: list[str], count: int
) -> str:
    mode = chapter.book.preference.mode if chapter.book.preference else "learn"
    if mode not in MODE_GUIDANCE:
        raise GenerationError(f"Unknown reading mode: {mode}")
    guidance = MODE_GUIDANCE[mode]
    prior = (
        "\n".join(f"- {title}" for title in prior_titles)
        if prior_titles
        else "(this is the first chapter)"
    )
    return (
        f"Book: {book_title}\n"
        f"Reading mode: {mode}\n"
        f"Companion focus: {guidance}\n"
        f"Chapters read so far:\n{prior}\n\n"
        f"Current chapter: {chapter.title}\n\n"
        f"Generate {count} questions for this chapter.\n\n"
        f"--- CHAPTER TEXT ---\n{chapter.text}"
    )


def build_worker_prompt(
    book_title: str, chapter: Chapter, prior_titles: list[str], count: int = 5
) -> str:
    """Single self-contained prompt for CLI workers (codex exec / claude -p),
    which have no separate system-prompt channel."""
    return (
        f"{SYSTEM_PROMPT}\n"
        "Return JSON only, matching the provided schema. No Markdown fences, "
        "no prose outside the JSON.\n\n"
        f"{_build_user_prompt(book_title, chapter, prior_titles, count)}"
    )


def parse_raw_output(raw: str) -> GeneratedMaterial:
    """Parse worker output into chapter material, tolerating Markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Worker output was not valid JSON: {exc}") from exc
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise GenerationError("Worker output contained no questions.")
    recap = data.get("recap") if isinstance(data, dict) else None
    if not isinstance(recap, str) or not recap.strip():
        raise GenerationError("Worker output contained no chapter recap.")
    questions = []
    for item in items:
        try:
            question = GeneratedQuestion(
                type=item["type"],
                prompt=item["prompt"],
                answer=item["answer"],
                source_quote=item["source_quote"],
            )
        except (TypeError, KeyError) as exc:
            raise GenerationError(f"Question missing field: {exc}") from exc
        if question.type not in QUESTION_TYPES:
            raise GenerationError(f"Unknown question type: {question.type}")
        if (
            not isinstance(question.source_quote, str)
            or not question.source_quote.strip()
        ):
            raise GenerationError("Question source_quote must not be blank.")
        questions.append(question)
    return GeneratedMaterial(recap=recap.strip(), questions=questions)


def generate_material(
    chapter: Chapter,
    prior_titles: list[str],
    book_title: str,
    count: int = 5,
    client: anthropic.Anthropic | None = None,
) -> GeneratedMaterial:
    settings = get_settings()
    if client is None:
        if not settings.anthropic_api_key:
            raise GenerationError(
                "ANTHROPIC_API_KEY is not configured; cannot generate questions."
            )
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": QUESTION_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": _build_user_prompt(book_title, chapter, prior_titles, count),
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise GenerationError("The model declined to generate questions.")

    text = next(
        (block.text for block in response.content if block.type == "text"), None
    )
    if text is None:
        raise GenerationError("The model returned no text content.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Model output was not valid JSON: {exc}") from exc

    recap = data.get("recap", "")
    if not isinstance(recap, str) or not recap.strip():
        raise GenerationError("The model returned no chapter recap.")
    questions = []
    for item in data.get("questions", []):
        try:
            question = GeneratedQuestion(
                type=item["type"],
                prompt=item["prompt"],
                answer=item["answer"],
                source_quote=item["source_quote"],
            )
        except (TypeError, KeyError) as exc:
            raise GenerationError(f"Question missing field: {exc}") from exc
        if question.type not in QUESTION_TYPES:
            raise GenerationError(f"Unknown question type: {question.type}")
        if (
            not isinstance(question.source_quote, str)
            or not question.source_quote.strip()
        ):
            raise GenerationError("Question source_quote must not be blank.")
        questions.append(question)
    if not questions:
        raise GenerationError("The model returned no questions.")
    return GeneratedMaterial(recap=recap.strip(), questions=questions)


def generate_questions(
    chapter: Chapter,
    prior_titles: list[str],
    book_title: str,
    count: int = 5,
    client: anthropic.Anthropic | None = None,
) -> list[GeneratedQuestion]:
    """Compatibility interface for callers that only need questions."""
    return generate_material(
        chapter, prior_titles, book_title, count=count, client=client
    ).questions


def store_questions(
    db: Session, chapter: Chapter, generated: list[GeneratedQuestion]
) -> list[Question]:
    """Persist a new generation batch and retire the previous one."""
    if any(not item.source_quote.strip() for item in generated):
        raise GenerationError("Question source_quote must not be blank.")
    latest = db.execute(
        select(func.max(Question.batch_version)).where(
            Question.chapter_id == chapter.id
        )
    ).scalar()
    version = (latest or 0) + 1

    for old in db.execute(
        select(Question).where(Question.chapter_id == chapter.id, Question.active)
    ).scalars():
        old.active = False

    questions = [
        Question(
            chapter_id=chapter.id,
            type=item.type,
            prompt=item.prompt,
            answer=item.answer,
            source_quote=item.source_quote,
            batch_version=version,
        )
        for item in generated
    ]
    db.add_all(questions)
    db.commit()
    return questions


def store_material(
    db: Session, chapter: Chapter, material: GeneratedMaterial
) -> list[Question]:
    """Store generated questions and the recap used by the next chapter."""
    questions = store_questions(db, chapter, material.questions)
    companion = db.execute(
        select(ChapterCompanion).where(ChapterCompanion.chapter_id == chapter.id)
    ).scalar_one_or_none()
    if companion is None:
        companion = ChapterCompanion(chapter_id=chapter.id)
        db.add(companion)
    companion.recap = material.recap
    db.commit()
    return questions
