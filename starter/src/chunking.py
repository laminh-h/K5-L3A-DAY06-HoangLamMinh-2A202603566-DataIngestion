"""Fixed-size and structure-aware (paragraph) chunking.

Both strategies chunk the *same* joined page text (see ingestion.join_lines), so every
chunk is an exact slice text[char_start:char_end] of its page and can be traced back.
Chunks never cross page boundaries (keeps `page` metadata exact; noted as a limitation).
"""
from __future__ import annotations

import hashlib
import re

from .ingestion import join_lines
from .models import Chunk, DocumentPage

# Numbered paragraph starts used in both reports: "1.22. ", "2.5. ", "12. "
_NUMBERED_RE = re.compile(r"^(\d{1,2}\.){1,2}\s")
_CAPTION_RE = re.compile(r"^(Figure|Table|Box|Source|Souce)\b", re.I)
_SENTENCE_END_RE = re.compile(r"[.:;?!)]$")
_FULL_LINE = 95  # typical extracted line length in these PDFs; shorter + sentence end = paragraph end


def _chunk(page: DocumentPage, strategy: str, index: int, text: str, start: int, end: int) -> Chunk:
    chunk_id = f"{strategy}:{page.document_id}:p{page.page:03d}:c{index:02d}"
    meta = dict(page.metadata)
    meta.update({
        "strategy": strategy, "chunk_index": index, "char_start": start, "char_end": end,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    })
    return Chunk(chunk_id=chunk_id, document_id=page.document_id, source=page.source,
                 page=page.page, text=text, metadata=meta)


def page_text(page: DocumentPage) -> tuple[str, list[tuple[int, int]]]:
    return join_lines([line for line in page.text.splitlines() if line])


def fixed_size(page: DocumentPage, size: int, overlap: int, strategy: str = "A") -> list[Chunk]:
    """Character windows of `size` with `overlap`, no regard for sentence/paragraph structure."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    text, _ = page_text(page)
    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end]
        if piece.strip():
            chunks.append(_chunk(page, strategy, len(chunks), piece, start, end))
        if end == len(text):
            break
        start += step
    return chunks


def paragraph_spans(lines: list[str], spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Group line spans into paragraph spans using numbering, captions and short-line endings."""
    paras: list[list[int]] = []  # each item: [start, end]
    for i, line in enumerate(lines):
        start, end = spans[i]
        new_para = (
            i == 0
            or bool(_NUMBERED_RE.match(line))
            or bool(_CAPTION_RE.match(line))
            or bool(_CAPTION_RE.match(lines[i - 1]))
            or (len(lines[i - 1]) < _FULL_LINE and bool(_SENTENCE_END_RE.search(lines[i - 1])))
        )
        if new_para:
            paras.append([start, end])
        else:
            paras[-1][1] = end
    return [(a, b) for a, b in paras]


def _merge_headings(text: str, paras: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Attach short heading-like paragraphs (no sentence end) to the paragraph that follows."""
    merged: list[tuple[int, int]] = []
    carry: int | None = None
    for a, b in paras:
        piece = text[a:b].strip()
        is_heading = (len(piece) < 160 and not _SENTENCE_END_RE.search(piece)
                      and not _CAPTION_RE.match(piece) and not _NUMBERED_RE.match(piece))
        if carry is not None:
            a = carry
            carry = None
        if is_heading:
            carry = a
            continue
        merged.append((a, b))
    if carry is not None:
        if merged:
            merged[-1] = (merged[-1][0], paras[-1][1])
        else:
            merged.append((carry, paras[-1][1]))
    return merged


def _split_long(text: str, a: int, b: int, max_size: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence boundaries (fallback: word boundary)."""
    pieces: list[tuple[int, int]] = []
    bounds = [m.end() + a for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z(\"'])", text[a:b])]
    cur = a
    while b - cur > max_size:
        candidates = [x for x in bounds if cur < x <= cur + max_size]
        if candidates:
            cut = candidates[-1]
        else:
            space = text.rfind(" ", cur + 1, cur + max_size)
            cut = space + 1 if space > cur else cur + max_size
        pieces.append((cur, cut))
        cur = cut
    pieces.append((cur, b))
    return pieces


def by_paragraph(page: DocumentPage, max_size: int, strategy: str = "B") -> list[Chunk]:
    """Pack whole paragraphs into chunks of at most `max_size` characters.

    Oversized paragraphs are split at sentence boundaries. Headings are kept with the
    paragraph that follows them.
    """
    lines = [line for line in page.text.splitlines() if line]
    if not lines:
        return []
    text, spans = join_lines(lines)
    paras = _merge_headings(text, paragraph_spans(lines, spans))
    units: list[tuple[int, int]] = []
    for a, b in paras:
        units.extend(_split_long(text, a, b, max_size) if b - a > max_size else [(a, b)])
    chunks: list[Chunk] = []
    cur_a, cur_b = units[0]
    for a, b in units[1:]:
        if b - cur_a <= max_size:
            cur_b = b
        else:
            chunks.append(_chunk(page, strategy, len(chunks), text[cur_a:cur_b].strip(), cur_a, cur_b))
            cur_a, cur_b = a, b
    chunks.append(_chunk(page, strategy, len(chunks), text[cur_a:cur_b].strip(), cur_a, cur_b))
    return [c for c in chunks if c.text]
