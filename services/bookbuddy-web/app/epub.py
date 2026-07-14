"""Structure-aware EPUB parsing.

Chapters come from the EPUB's real structure: the OPF spine gives reading
order and the nav/NCX table of contents gives chapter titles and boundaries.
When the TOC is missing or too flat to be useful, each spine document becomes
its own chapter, so no content is ever silently dropped.
"""

from __future__ import annotations

import posixpath
import warnings
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from ebooklib import ITEM_DOCUMENT, epub


@dataclass
class ParsedChapter:
    title: str
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class ParsedBook:
    title: str
    author: str
    chapters: list[ParsedChapter] = field(default_factory=list)


def _html_to_text(content: bytes) -> str:
    # EPUB documents are XHTML; lxml's HTML parser handles them fine but
    # warns about it. lxml-xml would break on HTML-isms in real books.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(content, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _href_key(href: str) -> str:
    path = unquote(urlparse(href).path)
    return posixpath.basename(path)


def _flatten_toc(toc: list) -> list[tuple[str, str]]:
    """Depth-first (href, title) pairs from ebooklib's nested TOC."""
    entries: list[tuple[str, str]] = []
    for node in toc:
        if isinstance(node, tuple):
            section, children = node
            href = getattr(section, "href", "")
            title = getattr(section, "title", "")
            if href:
                entries.append((href, title))
            entries.extend(_flatten_toc(list(children)))
        elif isinstance(node, epub.Link):
            entries.append((node.href, node.title))
    return entries


def _metadata_value(book: epub.EpubBook, name: str) -> str:
    values = book.get_metadata("DC", name)
    return values[0][0] if values else ""


FRONT_MATTER_MIN_WORDS = 100


def parse_epub(path: str) -> ParsedBook:
    book = epub.read_epub(path)
    title = _metadata_value(book, "title") or "Untitled"
    author = _metadata_value(book, "creator")

    spine_docs = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is not None and item.get_type() == ITEM_DOCUMENT:
            spine_docs.append(item)

    toc_titles: dict[str, str] = {}
    for href, toc_title in _flatten_toc(book.toc):
        toc_titles.setdefault(_href_key(href), toc_title)

    spine_keys = {_href_key(item.file_name) for item in spine_docs}
    matched = spine_keys & set(toc_titles)

    parsed = ParsedBook(title=title, author=author)
    if len(matched) >= 2:
        parsed.chapters = _chapters_from_toc(spine_docs, toc_titles)
    else:
        parsed.chapters = _chapters_from_spine(spine_docs)
    return parsed


def _chapters_from_toc(
    spine_docs: list, toc_titles: dict[str, str]
) -> list[ParsedChapter]:
    chapters: list[ParsedChapter] = []
    current_title: str | None = None
    current_parts: list[str] = []
    front_parts: list[str] = []

    def flush() -> None:
        if current_title is None:
            return
        text = "\n".join(part for part in current_parts if part)
        chapters.append(ParsedChapter(title=current_title, text=text))

    for item in spine_docs:
        key = _href_key(item.file_name)
        text = _html_to_text(item.get_content())
        if key in toc_titles:
            flush()
            current_title = toc_titles[key] or f"Chapter {len(chapters) + 1}"
            current_parts = [text]
        elif current_title is None:
            front_parts.append(text)
        else:
            current_parts.append(text)
    flush()

    front_text = "\n".join(part for part in front_parts if part)
    if len(front_text.split()) >= FRONT_MATTER_MIN_WORDS:
        chapters.insert(0, ParsedChapter(title="Front matter", text=front_text))
    return chapters


def _chapters_from_spine(spine_docs: list) -> list[ParsedChapter]:
    chapters: list[ParsedChapter] = []
    for item in spine_docs:
        text = _html_to_text(item.get_content())
        if not text.strip():
            continue
        chapters.append(ParsedChapter(title=f"Chapter {len(chapters) + 1}", text=text))
    return chapters
