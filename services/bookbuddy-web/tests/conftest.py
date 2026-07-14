import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="bookbuddy-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402
from ebooklib import epub  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402


def make_epub(path: Path, with_toc: bool = True, title: str = "Test Book") -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"test-{title}")
    book.set_title(title)
    book.set_language("en")
    book.add_author("Test Author")

    chapters = []
    for i in range(1, 4):
        chapter = epub.EpubHtml(
            title=f"Chapter {i}", file_name=f"chap_{i}.xhtml", lang="en"
        )
        body = f"<h1>Chapter {i}</h1><p>Story text of chapter {i}. "
        body += "word " * 40 + "</p>"
        chapter.content = body
        book.add_item(chapter)
        chapters.append(chapter)

    if with_toc:
        book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]
    epub.write_epub(str(path), book)
    return path


@pytest.fixture(scope="session")
def epub_path(tmp_path_factory) -> Path:
    return make_epub(tmp_path_factory.mktemp("epubs") / "test.epub")


@pytest.fixture(scope="session")
def epub_path_no_toc(tmp_path_factory) -> Path:
    return make_epub(
        tmp_path_factory.mktemp("epubs") / "no-toc.epub",
        with_toc=False,
        title="Flat Book",
    )


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    init_db()
    with SessionLocal() as session:
        yield session
