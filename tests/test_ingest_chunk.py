"""Chunking: sizes, boundaries, overlap, and text without spaces (Chinese)."""

import pytest

from lighthouse.ingest.chunk import chunk_text

# Numbered, so every sentence is unique and a chunk can be located in the text.
ENGLISH = "\n\n".join(
    " ".join(f"Sentence {p}.{s} says that sleep helps memory consolidation." for s in range(8)) for p in range(12)
)
CHINESE = "".join(f"第{i}句：充足的睡眠有助于巩固记忆，这一点已被多项研究证实。" for i in range(150))


def assert_covers(text: str, chunks: list[str], size: int, overlap: int) -> None:
    """Every chunk is a slice of `text`, within `size`, and together they leave no gap."""
    covered = 0  # everything before this position is in some chunk
    for chunk in chunks:
        assert len(chunk) <= size
        start = text.find(chunk, max(0, covered - overlap))
        assert start != -1, "a chunk must be an exact slice of the text"
        assert text[covered:start].strip() == "", "text was lost between two chunks"
        covered = start + len(chunk)
    assert text[covered:].strip() == ""


def shared_overlap(previous: str, following: str) -> int:
    """Length of the longest end of `previous` that `following` starts with."""
    return max((n for n in range(1, len(following)) if previous.endswith(following[:n])), default=0)


def test_short_input_is_one_chunk() -> None:
    assert chunk_text("  Just one line.\n") == ["Just one line."]
    assert chunk_text("") == []
    assert chunk_text(" \n\n ") == []


def test_english_breaks_on_sentences_and_loses_nothing() -> None:
    chunks = chunk_text(ENGLISH)
    assert len(chunks) > 5
    assert_covers(ENGLISH, chunks, size=1000, overlap=150)
    assert all(chunk.endswith(".") for chunk in chunks)
    assert all(len(chunk) > 500 for chunk in chunks[:-1]), "chunks should be filled, not tiny"


def test_consecutive_chunks_overlap() -> None:
    chunks = chunk_text(ENGLISH)
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert 50 <= shared_overlap(previous, following) <= 150
        # The overlap starts at a word boundary, not in the middle of a word.
        assert following.split()[0] in previous.split()


def test_chinese_text_without_spaces() -> None:
    chunks = chunk_text(CHINESE)
    assert len(chunks) > 3
    assert_covers(CHINESE, chunks, size=1000, overlap=150)
    assert all(chunk.endswith("。") for chunk in chunks), "should break after a sentence, not inside one"
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert 100 <= shared_overlap(previous, following) <= 150


def test_paragraph_boundary_is_preferred() -> None:
    paragraphs = [f"Paragraph {i}. " + "word " * 75 + "end." for i in range(3)]  # about 400 characters each
    chunks = chunk_text("\n\n".join(paragraphs))
    assert chunks[0] == paragraphs[0] + "\n\n" + paragraphs[1]
    assert chunks[1].endswith(paragraphs[2])


def test_text_without_any_boundary_is_cut_hard() -> None:
    text = "".join(f"{i:04d}" for i in range(750))  # 3000 characters, no punctuation or spaces
    chunks = chunk_text(text)
    assert_covers(text, chunks, size=1000, overlap=150)


def test_custom_size_and_no_overlap() -> None:
    chunks = chunk_text(ENGLISH, size=300, overlap=0)
    assert_covers(ENGLISH, chunks, size=300, overlap=0)
    assert "".join(chunks).count("Sentence") == ENGLISH.count("Sentence"), "no overlap: nothing appears twice"


def test_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValueError):
        chunk_text("text", size=100, overlap=100)
