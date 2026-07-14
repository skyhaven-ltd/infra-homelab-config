import json
from dataclasses import replace

import pytest

import app.main as main_module
from app.database import SessionLocal
from app.models import Book, GenerationJob, Question
from tests.test_flows import _import_book

TOKEN = "test-worker-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

VALID_OUTPUT = json.dumps(
    {
        "recap": (
            "The chapter established the central conflict and its first consequence."
        ),
        "questions": [
            {
                "type": "plot",
                "prompt": "Why?",
                "answer": "Because.",
                "source_quote": "Story text",
            }
        ],
    }
)


@pytest.fixture()
def worker_settings(monkeypatch):
    monkeypatch.setattr(
        main_module, "settings", replace(main_module.settings, worker_token=TOKEN)
    )
    # The suite shares one database; drop leftover jobs so claim order is
    # deterministic per test.
    with SessionLocal() as db:
        db.query(GenerationJob).delete()
        db.commit()


def _queue_job(client, epub_path) -> tuple[int, int]:
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter_id = db.get(Book, book_id).chapters[0].id
    response = client.post(f"/chapters/{chapter_id}/generate", follow_redirects=False)
    assert response.status_code == 303
    assert "notice=" in response.headers["location"]
    return book_id, chapter_id


def test_worker_endpoints_503_without_token_configured(client):
    response = client.post("/worker/generation-jobs/claim", headers=AUTH)
    assert response.status_code == 503


def test_worker_rejects_bad_token(client, worker_settings):
    response = client.post(
        "/worker/generation-jobs/claim",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


def test_claim_returns_none_when_queue_empty(client, worker_settings):
    response = client.post("/worker/generation-jobs/claim", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"job": None}


def test_import_queues_the_first_chapter_for_preparation(
    client, epub_path, worker_settings
):
    book_id = _import_book(client, epub_path)

    companion = client.get(f"/books/{book_id}/companion")
    assert "preparing your end-of-chapter questions" in companion.text
    assert "I've finished reading" not in companion.text

    claimed = client.post("/worker/generation-jobs/claim", headers=AUTH).json()
    assert claimed["job"]["chapter_title"] == "Chapter 1"


def test_imported_reading_mode_shapes_the_companion_prompt(
    client, epub_path, worker_settings
):
    with open(epub_path, "rb") as f:
        confirmation = client.post(
            "/books/upload",
            files={"file": ("test.epub", f, "application/epub+zip")},
        )
    assert 'name="mode"' in confirmation.text
    token = confirmation.text.split('name="token" value="')[1].split('"')[0]
    client.post(
        "/books/import",
        data={
            "token": token,
            "mode": "story",
            "chapter_indexes": ["0", "1", "2"],
        },
    )

    claimed = client.post("/worker/generation-jobs/claim", headers=AUTH).json()
    assert "Reading mode: story" in claimed["job"]["prompt"]
    assert "character motivations and unresolved threads" in claimed["job"]["prompt"]


def test_selecting_a_chapter_queues_it_for_preparation(
    client, epub_path, worker_settings
):
    book_id = _import_book(client, epub_path)
    first = client.post("/worker/generation-jobs/claim", headers=AUTH).json()["job"]
    client.post(
        f"/worker/generation-jobs/{first['id']}/fail",
        headers=AUTH,
        json={"error": "not needed for this test"},
    )

    selected = client.post(
        f"/books/{book_id}/position",
        data={"chapter_index": "1"},
        follow_redirects=False,
    )
    assert selected.status_code == 303

    claimed = client.post("/worker/generation-jobs/claim", headers=AUTH).json()
    assert claimed["job"]["chapter_title"] == "Chapter 2"


def test_generate_without_api_key_queues_job(client, epub_path, worker_settings):
    _, chapter_id = _queue_job(client, epub_path)
    with SessionLocal() as db:
        job = (
            db.query(GenerationJob).filter(GenerationJob.chapter_id == chapter_id).one()
        )
        assert job.status == "pending"

    # Re-posting generate must not duplicate the pending job
    client.post(f"/chapters/{chapter_id}/generate", follow_redirects=False)
    with SessionLocal() as db:
        count = (
            db.query(GenerationJob)
            .filter(GenerationJob.chapter_id == chapter_id)
            .count()
        )
        assert count == 1


def test_removing_book_removes_its_queued_generation_jobs(
    client, epub_path, worker_settings
):
    book_id, _ = _queue_job(client, epub_path)

    removed = client.post(
        f"/books/{book_id}/delete",
        data={"confirmation": "remove"},
        follow_redirects=False,
    )
    assert removed.status_code == 303

    claimed = client.post("/worker/generation-jobs/claim", headers=AUTH)
    assert claimed.json() == {"job": None}


def test_claim_complete_creates_questions(client, epub_path, worker_settings):
    _, chapter_id = _queue_job(client, epub_path)

    claimed = client.post("/worker/generation-jobs/claim", headers=AUTH).json()
    job = claimed["job"]
    assert job is not None
    assert "Story text of chapter 1" in job["prompt"]
    assert "Make It Stick" in job["prompt"]

    response = client.post(
        f"/worker/generation-jobs/{job['id']}/complete",
        headers=AUTH,
        json={"raw_output": VALID_OUTPUT},
    )
    assert response.status_code == 200
    assert response.json() == {"questions_created": 1}

    with SessionLocal() as db:
        stored_job = db.get(GenerationJob, job["id"])
        assert stored_job.status == "succeeded"
        questions = (
            db.query(Question)
            .filter(Question.chapter_id == chapter_id, Question.active)
            .all()
        )
        assert len(questions) == 1
        assert questions[0].prompt == "Why?"


def test_completed_chapter_recap_greets_reader_at_the_next_chapter(
    client, epub_path, worker_settings
):
    book_id, chapter_id = _queue_job(client, epub_path)
    job = client.post("/worker/generation-jobs/claim", headers=AUTH).json()["job"]
    completed = client.post(
        f"/worker/generation-jobs/{job['id']}/complete",
        headers=AUTH,
        json={"raw_output": VALID_OUTPUT},
    )
    assert completed.status_code == 200
    client.post(
        f"/chapters/{chapter_id}/prediction",
        data={"prediction": "The conflict will force the group apart."},
    )

    quiz = client.get(f"/chapters/{chapter_id}/quiz")
    question_id = quiz.text.split('name="question_id" value="')[1].split('"')[0]
    client.post(
        f"/chapters/{chapter_id}/quiz",
        data={
            "question_id": question_id,
            "answer_text": "Because of the conflict.",
            "confidence": "3",
        },
    )
    graded = client.post(
        f"/chapters/{chapter_id}/grade",
        data={
            "question_id": question_id,
            "answer_text": "Because of the conflict.",
            "confidence": "3",
            "correct": "yes",
        },
        follow_redirects=False,
    )

    companion = client.get(graded.headers["location"])
    assert "<h1>Chapter 2</h1>" in companion.text
    assert "Previously on Test Book" in companion.text
    assert "The chapter established the central conflict" in companion.text
    assert "Your prediction, revisited" in companion.text
    assert "The conflict will force the group apart." in companion.text

    reflected = client.post(
        f"/chapters/{chapter_id}/prediction-reflection",
        data={"reflection": "I noticed the consequence but missed who caused it."},
        follow_redirects=False,
    )
    companion = client.get(reflected.headers["location"])
    assert "I noticed the consequence but missed who caused it." in companion.text


def test_complete_with_invalid_output_fails_job(client, epub_path, worker_settings):
    _queue_job(client, epub_path)
    job = client.post("/worker/generation-jobs/claim", headers=AUTH).json()["job"]

    response = client.post(
        f"/worker/generation-jobs/{job['id']}/complete",
        headers=AUTH,
        json={"raw_output": "not json at all"},
    )
    assert response.status_code == 422

    with SessionLocal() as db:
        assert db.get(GenerationJob, job["id"]).status == "failed"


def test_complete_accepts_fenced_json(client, epub_path, worker_settings):
    _queue_job(client, epub_path)
    job = client.post("/worker/generation-jobs/claim", headers=AUTH).json()["job"]
    fenced = f"```json\n{VALID_OUTPUT}\n```"
    response = client.post(
        f"/worker/generation-jobs/{job['id']}/complete",
        headers=AUTH,
        json={"raw_output": fenced},
    )
    assert response.status_code == 200


def test_fail_endpoint_records_error(client, epub_path, worker_settings):
    _queue_job(client, epub_path)
    job = client.post("/worker/generation-jobs/claim", headers=AUTH).json()["job"]
    response = client.post(
        f"/worker/generation-jobs/{job['id']}/fail",
        headers=AUTH,
        json={"error": "codex exploded"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        stored = db.get(GenerationJob, job["id"])
        assert stored.status == "failed"
        assert stored.error == "codex exploded"

    # A settled job cannot be completed afterwards
    response = client.post(
        f"/worker/generation-jobs/{job['id']}/complete",
        headers=AUTH,
        json={"raw_output": VALID_OUTPUT},
    )
    assert response.status_code == 409
