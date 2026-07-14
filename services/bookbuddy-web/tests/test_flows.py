from app.database import SessionLocal
from app.models import Book, Question, ReviewState, utcnow


def _import_book(client, epub_path) -> int:
    with open(epub_path, "rb") as f:
        response = client.post(
            "/books/upload",
            files={"file": ("test.epub", f, "application/epub+zip")},
        )
    assert response.status_code == 200
    assert "Chapter 1" in response.text
    token = response.text.split('name="token" value="')[1].split('"')[0]

    response = client.post(
        "/books/import",
        data={
            "token": token,
            "mode": "learn",
            "chapter_indexes": ["0", "1", "2"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def test_import_flow_creates_book_and_chapters(client, epub_path):
    book_id = _import_book(client, epub_path)
    response = client.get(f"/books/{book_id}")
    assert response.status_code == 200
    assert "Chapter 1" in response.text
    assert "Continue" in response.text
    assert "Read from here" in response.text
    assert "Generate questions" not in response.text

    home = client.get("/")
    assert "Continue reading" in home.text
    assert f'href="http://testserver/books/{book_id}/companion"' in home.text


def test_import_flow_can_include_only_selected_chapters(client, epub_path):
    with open(epub_path, "rb") as f:
        confirmation = client.post(
            "/books/upload",
            files={"file": ("test.epub", f, "application/epub+zip")},
        )

    assert 'name="chapter_indexes"' in confirmation.text
    token = confirmation.text.split('name="token" value="')[1].split('"')[0]

    imported = client.post(
        "/books/import",
        data={"token": token, "mode": "learn", "chapter_indexes": "1"},
        follow_redirects=False,
    )
    book_id = int(imported.headers["location"].rsplit("/", 1)[1])

    detail = client.get(f"/books/{book_id}")
    assert '<span class="toc-title">Chapter 2</span>' in detail.text
    assert '<span class="toc-title">Chapter 1</span>' not in detail.text
    assert '<span class="toc-title">Chapter 3</span>' not in detail.text


def test_import_requires_a_chapter_and_allows_retry(client, epub_path):
    with open(epub_path, "rb") as f:
        confirmation = client.post(
            "/books/upload",
            files={"file": ("test.epub", f, "application/epub+zip")},
        )
    token = confirmation.text.split('name="token" value="')[1].split('"')[0]

    rejected = client.post("/books/import", data={"token": token, "mode": "learn"})
    assert rejected.status_code == 422
    assert "Choose at least one chapter" in rejected.text

    retried = client.post(
        "/books/import",
        data={"token": token, "mode": "learn", "chapter_indexes": "0"},
        follow_redirects=False,
    )
    assert retried.status_code == 303


def test_book_can_be_removed_after_confirmation(client, epub_path):
    book_id = _import_book(client, epub_path)

    confirmation = client.get(f"/books/{book_id}/delete")
    assert confirmation.status_code == 200
    assert "Remove Test Book?" in confirmation.text

    removed = client.post(
        f"/books/{book_id}/delete",
        data={"confirmation": "remove"},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert removed.headers["location"] == "/"
    assert client.get(f"/books/{book_id}").status_code == 404
    assert f"/books/{book_id}/companion" not in client.get("/").text


def test_import_rejects_bad_token(client):
    assert (
        client.post("/books/import", data={"token": "zzz", "mode": "learn"}).status_code
        == 400
    )
    token = "0" * 32
    assert (
        client.post("/books/import", data={"token": token, "mode": "learn"}).status_code
        == 404
    )


def test_upload_rejects_non_epub(client, tmp_path):
    bad = tmp_path / "not.epub"
    bad.write_bytes(b"definitely not an epub")
    with open(bad, "rb") as f:
        response = client.post(
            "/books/upload", files={"file": ("not.epub", f, "application/epub+zip")}
        )
    assert response.status_code == 422


def test_quiz_grade_records_attempts_and_schedules(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        book = db.get(Book, book_id)
        chapter_id = book.chapters[0].id
        question = Question(
            chapter_id=chapter_id,
            type="recall",
            prompt="What happened?",
            answer="Things.",
            source_quote="Story text",
        )
        db.add(question)
        db.commit()
        question_id = question.id

    response = client.get(f"/chapters/{chapter_id}/quiz")
    assert "What happened?" in response.text

    response = client.post(
        f"/chapters/{chapter_id}/quiz",
        data={
            "question_id": str(question_id),
            "answer_text": "Stuff",
            "confidence": "4",
        },
    )
    assert response.status_code == 200
    assert "Things." in response.text

    response = client.post(
        f"/chapters/{chapter_id}/grade",
        data={
            "question_id": str(question_id),
            "answer_text": "Stuff",
            "confidence": "4",
            "correct": "yes",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{book_id}/companion"

    companion = client.get(response.headers["location"])
    assert "<h1>Chapter 2</h1>" in companion.text

    with SessionLocal() as db:
        stored = db.get(Question, question_id)
        assert len(stored.attempts) == 1
        assert stored.attempts[0].correct is True
        assert stored.review is not None
        assert stored.review.interval_days == 1.0


def test_chapter_quiz_presents_one_typed_question_at_a_time(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter = db.get(Book, book_id).chapters[0]
        first = Question(
            chapter_id=chapter.id,
            type="recall",
            prompt="First prompt?",
            answer="First answer.",
        )
        second = Question(
            chapter_id=chapter.id,
            type="theme",
            prompt="Second prompt?",
            answer="Second answer.",
        )
        db.add_all([first, second])
        db.commit()
        chapter_id = chapter.id
        first_id = first.id

    question = client.get(f"/chapters/{chapter_id}/quiz")
    assert "Question 1 of 2" in question.text
    assert "First prompt?" in question.text
    assert "Second prompt?" not in question.text

    reveal = client.post(
        f"/chapters/{chapter_id}/quiz",
        data={
            "question_id": str(first_id),
            "answer_text": "My first answer",
            "confidence": "4",
        },
    )
    assert "First answer." in reveal.text
    assert "Second prompt?" not in reveal.text

    graded = client.post(
        f"/chapters/{chapter_id}/grade",
        data={
            "question_id": str(first_id),
            "answer_text": "My first answer",
            "confidence": "4",
            "correct": "yes",
        },
        follow_redirects=False,
    )
    assert graded.status_code == 303
    assert graded.headers["location"] == f"/chapters/{chapter_id}/quiz"

    next_question = client.get(f"/chapters/{chapter_id}/quiz")
    assert "Question 2 of 2" in next_question.text
    assert "Second prompt?" in next_question.text
    assert "First prompt?" not in next_question.text
    assert "Quiz in progress" in client.get("/").text


def test_reader_can_save_a_prediction_for_the_current_chapter(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter_id = db.get(Book, book_id).chapters[0].id

    saved = client.post(
        f"/chapters/{chapter_id}/prediction",
        data={"prediction": "The guide is hiding something important."},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == f"/books/{book_id}/companion"

    companion = client.get(saved.headers["location"])
    assert "Your prediction" in companion.text
    assert "The guide is hiding something important." in companion.text

    quiz = client.get(f"/chapters/{chapter_id}/quiz")
    assert "Before reading, you predicted" in quiz.text
    assert "The guide is hiding something important." in quiz.text


def test_reader_can_capture_a_thought_without_leaving_the_chapter(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter_id = db.get(Book, book_id).chapters[0].id

    saved = client.post(
        f"/chapters/{chapter_id}/thoughts",
        data={"thought": "This rule contradicts the example from the introduction."},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == f"/books/{book_id}/companion"

    companion = client.get(saved.headers["location"])
    assert "Thoughts from this chapter" in companion.text
    assert "This rule contradicts the example" in companion.text


def test_reader_cannot_save_a_blank_thought(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter_id = db.get(Book, book_id).chapters[0].id

    response = client.post(f"/chapters/{chapter_id}/thoughts", data={"thought": "   "})

    assert response.status_code == 422


def test_existing_questions_provide_a_fallback_previously_on(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        first_chapter = db.get(Book, book_id).chapters[0]
        question = Question(
            chapter_id=first_chapter.id,
            type="plot",
            prompt="How did they escape?",
            answer="The party escaped through the abandoned gate.",
        )
        db.add(question)
        db.commit()
        chapter_id = first_chapter.id
        question_id = question.id

    client.post(
        f"/chapters/{chapter_id}/grade",
        data={
            "question_id": str(question_id),
            "answer_text": "Through the gate.",
            "confidence": "4",
            "correct": "yes",
        },
    )
    companion = client.get(f"/books/{book_id}/companion")
    assert "Previously on Test Book" in companion.text
    assert "The party escaped through the abandoned gate." in companion.text


def test_skipped_chapter_is_not_shown_as_previously_on(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        skipped_chapter = db.get(Book, book_id).chapters[1]
        db.add(
            Question(
                chapter_id=skipped_chapter.id,
                type="plot",
                prompt="What spoiler happened?",
                answer="A secret event the reader has not reached.",
            )
        )
        db.commit()

    client.post(
        f"/books/{book_id}/position",
        data={"chapter_index": "2"},
    )
    companion = client.get(f"/books/{book_id}/companion")
    assert "A secret event the reader has not reached." not in companion.text


def test_finishing_the_final_chapter_completes_the_book(client, epub_path):
    book_id = _import_book(client, epub_path)
    client.post(
        f"/books/{book_id}/position",
        data={"chapter_index": "2"},
    )
    with SessionLocal() as db:
        final_chapter = db.get(Book, book_id).chapters[2]
        question = Question(
            chapter_id=final_chapter.id,
            type="theme",
            prompt="What brought the book together?",
            answer="Its closing idea.",
        )
        db.add(question)
        db.commit()
        chapter_id = final_chapter.id
        question_id = question.id

    graded = client.post(
        f"/chapters/{chapter_id}/grade",
        data={
            "question_id": str(question_id),
            "answer_text": "The closing idea.",
            "confidence": "4",
            "correct": "yes",
        },
        follow_redirects=False,
    )
    companion = client.get(graded.headers["location"])
    assert "You finished Test Book" in companion.text
    assert "I've finished reading" not in companion.text


def test_companion_offers_due_memories_before_reading(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter = db.get(Book, book_id).chapters[0]
        question = Question(
            chapter_id=chapter.id,
            type="recall",
            prompt="What should return before reading?",
            answer="This memory.",
        )
        db.add(question)
        db.flush()
        db.add(ReviewState(question_id=question.id, due_at=utcnow()))
        db.commit()

    companion = client.get(f"/books/{book_id}/companion")
    assert "Before we continue" in companion.text
    assert "Warm up with 1 memory" in companion.text
    return_to = f"/books/{book_id}/companion"
    assert f"return_to={return_to}" in companion.text

    review = client.get(f"/review?return_to={return_to}")
    question_id = review.text.split("/review/")[1].split('"')[0]
    reveal = client.post(
        f"/review/{question_id}",
        data={
            "answer_text": "This memory.",
            "confidence": "4",
            "return_to": return_to,
        },
    )
    assert "This memory." in reveal.text
    graded = client.post(
        f"/review/{question_id}/grade",
        data={
            "answer_text": "This memory.",
            "confidence": "4",
            "correct": "yes",
            "return_to": return_to,
        },
        follow_redirects=False,
    )
    assert graded.headers["location"] == return_to


def test_review_flow_grades_due_question(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        book = db.get(Book, book_id)
        question = Question(
            chapter_id=book.chapters[0].id,
            type="theme",
            prompt="Theme?",
            answer="Perseverance.",
        )
        db.add(question)
        db.commit()
        question_id = question.id

    # No review state yet -> not due
    response = client.get("/review")
    assert response.status_code == 200

    response = client.post(
        f"/review/{question_id}",
        data={"answer_text": "Grit", "confidence": "2"},
    )
    assert "Perseverance." in response.text

    response = client.post(
        f"/review/{question_id}/grade",
        data={"answer_text": "Grit", "confidence": "2", "correct": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        stored = db.get(Question, question_id)
        assert stored.review is not None
        assert stored.attempts[0].confidence == 2


def test_generate_route_without_api_key_queues_for_worker(client, epub_path):
    book_id = _import_book(client, epub_path)
    with SessionLocal() as db:
        chapter_id = db.get(Book, book_id).chapters[0].id
    response = client.post(f"/chapters/{chapter_id}/generate", follow_redirects=False)
    assert response.status_code == 303
    assert "notice=" in response.headers["location"]

    response = client.get(f"/books/{book_id}")
    assert "generation pending" in response.text
