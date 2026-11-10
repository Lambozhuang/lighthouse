"""Split text into overlapping chunks for embedding. Pure functions, no I/O.

Sizes are in characters, not tokens: counting characters needs no tokenizer and works the same
for English and Chinese. 1000 characters is a few hundred tokens of English and around a
thousand of Chinese, both far below the embedding model's input limit (8191 tokens).
"""

import re
from collections.abc import Iterator

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

# Each pattern matches a separator; the text is cut right after it, so the pieces still join
# back to the original text.
_PARAGRAPH_END = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(
    r"""
      [.!?]["')\]]*\s+           # English: punctuation, then whitespace ("3.14" and "a.com" stay whole)
    | [。！？；…]+[”’」』）]*\s*    # Chinese: punctuation is enough, there is no space after it
    | \n+                        # a line break (list items, table rows)
    """,
    re.VERBOSE,
)


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Chunks of at most `size` characters; each one starts with the last ~`overlap` characters
    of the one before, so a fact that straddles a boundary is whole in at least one chunk."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be smaller than size")

    chunks: list[str] = []
    current = ""
    # Pieces are at most `size - overlap` long, so the overlap plus one piece always fits.
    for piece in _pieces(text.strip(), size - overlap):
        if current and len(current) + len(piece) > size:
            chunks.append(current.strip())
            current = _tail(current, overlap)
        current += piece
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _pieces(text: str, limit: int) -> Iterator[str]:
    """Cut `text` into pieces of at most `limit` characters, at the largest boundary that fits:
    paragraphs first, then sentences, and only as a last resort in the middle of a sentence."""
    for paragraph in _split_after(text, _PARAGRAPH_END):
        if len(paragraph) <= limit:
            yield paragraph
            continue
        for sentence in _split_after(paragraph, _SENTENCE_END):
            for start in range(0, len(sentence), limit):
                yield sentence[start : start + limit]


def _split_after(text: str, separator: re.Pattern[str]) -> list[str]:
    """Cut `text` after every match of `separator`. `"".join(result) == text`."""
    pieces: list[str] = []
    start = 0
    for match in separator.finditer(text):
        pieces.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    return pieces


def _tail(chunk: str, overlap: int) -> str:
    """The end of `chunk` that the next chunk repeats."""
    tail = chunk[-overlap:] if overlap else ""
    # Do not start in the middle of an English word: skip ahead to the first space. Only when
    # that space comes early, though. Chinese has no spaces between words, and one stray space
    # near the end of the tail must not throw the whole overlap away.
    words = tail.rstrip()
    space = re.search(r"\s", words)
    if space and space.end() <= len(words) // 2:
        tail = tail[space.end() :]
    return tail
