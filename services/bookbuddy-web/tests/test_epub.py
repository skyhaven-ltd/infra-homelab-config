from app.epub import parse_epub


def test_parses_chapters_from_toc(epub_path):
    parsed = parse_epub(str(epub_path))
    assert parsed.title == "Test Book"
    assert parsed.author == "Test Author"
    assert [c.title for c in parsed.chapters] == [
        "Chapter 1",
        "Chapter 2",
        "Chapter 3",
    ]
    assert all(c.word_count > 30 for c in parsed.chapters)
    assert "Story text of chapter 2" in parsed.chapters[1].text


def test_falls_back_to_spine_without_toc(epub_path_no_toc):
    parsed = parse_epub(str(epub_path_no_toc))
    assert parsed.title == "Flat Book"
    texts = "\n".join(c.text for c in parsed.chapters)
    for i in (1, 2, 3):
        assert f"Story text of chapter {i}" in texts
    assert all(c.title for c in parsed.chapters)
