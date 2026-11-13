"""Read and normalize source PDFs while keeping a link back to source/page."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

# Characters that pypdf returns for typographic punctuation / bullets.
_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    "­": "",          # soft hyphen
    "•": "-", "": "-", "": "-",  # bullets (incl. private-use glyphs)
    " ": " ",
}
_CHAR_TABLE = str.maketrans(_CHAR_MAP)

# Running header printed on every page of both reports.
_HEADER_RE = re.compile(r"^TAKING STOCK An Update on Vietnam's Recent Economic Developments$", re.I)
_PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")
# Chart residue: axis ticks / data labels extracted as standalone short lines.
_CHART_RESIDUE_RE = re.compile(r"^[\s\d.,%()+\-/:]*$")
_DISCLOSURE_RE = re.compile(r"^Public Disclosure Authori[sz]ed$", re.I)


@dataclass
class IngestLog:
    """Everything worth reporting about the read/normalize step."""
    empty_pages: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    removed_lines: dict[str, int] = field(default_factory=lambda: {"header": 0, "page_number": 0,
                                                                       "chart_residue": 0, "disclosure": 0})

    def to_dict(self) -> dict[str, Any]:
        return {"empty_pages": self.empty_pages, "errors": self.errors, "removed_lines": self.removed_lines}


def normalize_text(text: str) -> str:
    """Unicode NFKC + map typographic punctuation; collapse spaces but keep line structure."""
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_TABLE)
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def clean_lines(text: str, log: IngestLog | None = None) -> list[str]:
    """Drop running headers, bare page numbers and chart-axis residue lines."""
    kept: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        reason = None
        if _HEADER_RE.match(line):
            reason = "header"
        elif _PAGE_NUMBER_RE.match(line):
            reason = "page_number"
        elif _DISCLOSURE_RE.match(line):
            reason = "disclosure"
        elif _CHART_RESIDUE_RE.match(line):
            reason = "chart_residue"
        if reason:
            if log is not None:
                log.removed_lines[reason] += 1
            continue
        kept.append(line)
    return kept


def join_lines(lines: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Join extracted lines into one string; return the text and each line's (start, end) span.

    A line ending in '-' followed by a lowercase word is joined without a space
    (e.g. 'export-' + 'oriented' -> 'export-oriented'); otherwise lines are joined with one space.
    """
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, line in enumerate(lines):
        if i > 0:
            sep = "" if parts[-1].endswith("-") and line[:1].islower() else " "
            parts.append(sep)
            pos += len(sep)
        spans.append((pos, pos + len(line)))
        parts.append(line)
        pos += len(line)
    return "".join(parts), spans


def flatten(text: str) -> str:
    """Canonical single-line form used for evidence matching (case/whitespace-insensitive)."""
    text = normalize_text(text)
    text, _ = join_lines([line for line in text.splitlines() if line])
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_page_ranges(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        pages.extend(range(int(a), int(b or a) + 1))
    return pages


def load_pdf(path: Path, document_id: str, source: str, log: IngestLog | None = None) -> list[DocumentPage]:
    """Extract every physical page (1-based), normalize it and keep page number and source.

    Pages with no extractable text are returned with empty text and recorded in the log;
    OCR is not attempted (both reports are born-digital PDFs).
    """
    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # keep going, but record the failure
            raw = ""
            if log is not None:
                log.errors.append({"document_id": document_id, "page": number, "error": repr(exc)})
        text = normalize_text(raw)
        if not text and log is not None:
            log.empty_pages.append({"document_id": document_id, "page": number})
        pages.append(DocumentPage(document_id=document_id, source=source, page=number, text=text,
                                  metadata={"raw_chars": len(raw)}))
    return pages


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def section_for(page: int, sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for sec in sections:
        if page in parse_page_ranges(sec["pages"]):
            return sec
    return None


def load_corpus(root: Path, manifest: dict[str, Any], log: IngestLog) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Load all sources; return counted content pages (cleaned) and a per-page inventory."""
    content_pages: list[DocumentPage] = []
    inventory: list[dict[str, Any]] = []
    for src in manifest["sources"]:
        path = root / src["source_path_or_url"]
        if not path.exists():
            raise FileNotFoundError(f"Corpus file missing: {path} (see data/manifest.json for the download URL)")
        counted = set(parse_page_ranges(src["counted_pages"]))
        for page in load_pdf(path, src["source_id"], src["source_path_or_url"], log):
            lines = clean_lines(page.text, log if page.page in counted else None)
            joined, _ = join_lines(lines)
            is_counted = page.page in counted
            inventory.append({"document_id": src["source_id"], "page": page.page, "counted": is_counted,
                              "normalized_chars": len(joined), "raw_chars": page.metadata["raw_chars"]})
            if not is_counted:
                continue
            sec = section_for(page.page, src["sections"])
            page.text = "\n".join(lines)
            page.metadata = {
                "edition": src["edition"], "year": src["year"], "language": src["language"],
                "section": sec["section"] if sec else "unknown",
                "section_title": sec["title"] if sec else "unknown",
            }
            content_pages.append(page)
    return content_pages, inventory
