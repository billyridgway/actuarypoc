from __future__ import annotations

"""Document maps: partition a document's full text into page-anchored slices.

This module is the foundation of slice-based extraction (see
``docs/slice-extraction-plan.md``). It replaces the old "join all pages and
truncate to 50,000 chars" feeding strategy with a *map* of the document:
the canonical text (page texts joined by ``"\\n"``) is partitioned into
bounded slices, each carrying its page span, heading, and exact character
range, so downstream extractors can be dispatched over the whole document
and cite real pages.

Design invariants:

- **Coverage**: the union of ``[char_start, char_end)`` over all slices is
  exactly ``[0, total_chars)`` — every character belongs to at least one
  slice. (Size-cut slices additionally *overlap* their successor, so some
  characters belong to two slices; none belong to zero.)
- **Exactness**: for every slice, ``canonical[char_start:char_end]`` equals
  the slice text, where ``canonical`` is the page texts joined by ``"\\n"``.
- **Boundedness**: no slice exceeds ``max_chars`` characters.
- **Streaming build**: pages are consumed from a lazy iterable one at a
  time; the builder never materialises a joined full-text copy — peak
  extra memory is one page plus the current slice buffer plus the finished
  slices of the one document being mapped.

The module is pure (no I/O, no MinIO) so it is trivially testable; storage
of maps/slices as objects lives in ``slice_pipeline``.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_TARGET_CHARS = 4000
DEFAULT_MAX_CHARS = 6000
DEFAULT_MIN_CHARS = 800
DEFAULT_OVERLAP_CHARS = 300
_HEADING_MIN_SLICE_CHARS = 200
# A size cut that is due may move to a paragraph boundary (a blank
# line) whose end lands within this many characters of the target —
# prose reads better whole, and a charge statement split mid-sentence
# is harder for an extractor to interpret than one kept intact.
_PARAGRAPH_CUT_WINDOW = 800

_SECTION_PREFIX = re.compile(
    r"^(SECTION|ARTICLE|PART|CHAPTER|APPENDIX|EXHIBIT|SCHEDULE|ADDENDUM)\b",
    re.IGNORECASE,
)
_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.\s+\S")


def looks_like_heading(line: str) -> bool:
    """Deterministic, conservative heading heuristic for filing text."""

    stripped = (line or "").strip()
    if len(stripped) < 4 or len(stripped) > 90:
        return False
    if _SECTION_PREFIX.match(stripped):
        return True
    if _NUMBERED_HEADING.match(stripped):
        return True
    # ALL-CAPS line (letters present, no lowercase) reads as a heading in
    # filing typography, e.g. "GENERAL PROVISIONS".
    if any(c.isalpha() for c in stripped) and stripped == stripped.upper():
        return True
    return False


def doc_slug(doc_id: str) -> str:
    """Filesystem/object-key-safe slug for a document id."""

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(doc_id or "")).strip("-")
    return slug or "document"


@dataclass(frozen=True)
class DocumentSlice:
    slice_id: str
    doc_id: str
    document_hint: str
    page_start: Optional[int]
    page_end: Optional[int]
    heading: Optional[str]
    char_start: int
    char_end: int
    text: str
    # (offset within the slice text, page) marks where each page's text
    # begins inside this slice — lets evidence be re-anchored to the exact
    # page. Empty for page-less slices.
    page_offsets: Tuple[Tuple[int, int], ...] = ()

    @property
    def char_count(self) -> int:
        return self.char_end - self.char_start

    def page_at_offset(self, offset: int) -> Optional[int]:
        """Page containing ``offset`` (relative to the slice text start)."""

        page: Optional[int] = self.page_start
        for rel, pg in self.page_offsets:
            if offset >= rel:
                page = pg
            else:
                break
        return page

    def page_segments(self) -> List[Tuple[str, Optional[int]]]:
        """The slice text split into (segment, page) runs by page."""

        if not self.page_offsets:
            return [(self.text, self.page_start)]
        segments: List[Tuple[str, Optional[int]]] = []
        marks = list(self.page_offsets)
        for i, (rel, pg) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(self.text)
            segments.append((self.text[rel:end], pg))
        return segments

    def descriptor(self) -> Dict[str, Any]:
        """Slice metadata without the text (what the map stores inline)."""

        return {
            "slice_id": self.slice_id,
            "doc_id": self.doc_id,
            "document_hint": self.document_hint,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "heading": self.heading,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "char_count": self.char_count,
            "page_offsets": [list(p) for p in self.page_offsets],
        }

    def to_dict(self) -> Dict[str, Any]:
        data = self.descriptor()
        data["text"] = self.text
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentSlice":
        return cls(
            slice_id=str(data["slice_id"]),
            doc_id=str(data["doc_id"]),
            document_hint=str(data.get("document_hint") or ""),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            heading=data.get("heading"),
            char_start=int(data["char_start"]),
            char_end=int(data["char_end"]),
            text=str(data.get("text") or ""),
            page_offsets=tuple(
                (int(rel), int(pg)) for rel, pg in (data.get("page_offsets") or [])
            ),
        )


@dataclass
class DocumentMap:
    doc_id: str
    document_hint: str
    object_path: Optional[str]
    page_count: int
    total_chars: int
    slices: List[DocumentSlice] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "document_hint": self.document_hint,
            "object_path": self.object_path,
            "page_count": self.page_count,
            "total_chars": self.total_chars,
            "slice_count": len(self.slices),
            "slices": [s.descriptor() for s in self.slices],
        }

    def slices_payload(self) -> Dict[str, Any]:
        """Full slice records (with text) for the slices object."""

        return {
            "doc_id": self.doc_id,
            "document_hint": self.document_hint,
            "slices": [s.to_dict() for s in self.slices],
        }

    @classmethod
    def from_slices_payload(
        cls, payload: Dict[str, Any], *, object_path: Optional[str] = None
    ) -> "DocumentMap":
        slices = [DocumentSlice.from_dict(s) for s in payload.get("slices") or []]
        total = max((s.char_end for s in slices), default=0)
        pages = [s.page_end for s in slices if s.page_end is not None]
        return cls(
            doc_id=str(payload.get("doc_id") or ""),
            document_hint=str(payload.get("document_hint") or ""),
            object_path=object_path,
            page_count=max(pages) if pages else 0,
            total_chars=total,
            slices=slices,
        )


# ---------------------------------------------------------------------------
# Line stream
# ---------------------------------------------------------------------------


@dataclass
class _Line:
    text: str
    start: int  # canonical offset of the first char
    end: int  # canonical offset just past the last char (newline excluded)
    page: Optional[int]
    # Canonical offset just past this line's trailing newline, when the
    # line is followed by one; equals ``end`` for the document's last
    # line. Slices use it so the separator newline between two slices is
    # owned by the earlier slice and coverage has no 1-char gaps.
    end_incl: int = -1


def _iter_lines(
    pages: Iterable[str], *, paged: bool
) -> Tuple[List[_Line], int, int]:
    """Materialise the line stream for one document.

    Lines are the document's lines in canonical order with exact canonical
    offsets. ``pages`` is consumed lazily, one page at a time; the joined
    full text is never built.
    """

    lines: List[_Line] = []
    offset = 0
    page_count = 0
    for page_index, page_text in enumerate(pages):
        page_count += 1
        page_no: Optional[int] = (page_index + 1) if paged else None
        if page_index > 0:
            offset += 1  # the "\n" joiner between pages in canonical text
        parts = str(page_text or "").split("\n")
        for i, part in enumerate(parts):
            start = offset
            end = start + len(part)
            lines.append(_Line(text=part, start=start, end=end, page=page_no))
            offset = end
            if i < len(parts) - 1:
                offset += 1  # newline inside the page text
    total_chars = offset
    # Consecutive lines are separated by exactly one canonical char (the
    # newline), so each line's inclusive end is the next line's start.
    for i, line in enumerate(lines):
        line.end_incl = lines[i + 1].start if i + 1 < len(lines) else line.end
    return lines, page_count, total_chars


def _slice_text(lines: List[_Line]) -> str:
    return "\n".join(line.text for line in lines)


def _make_slice(
    *,
    index: int,
    doc_id: str,
    document_hint: str,
    lines: List[_Line],
    heading: Optional[str],
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
    text: Optional[str] = None,
) -> DocumentSlice:
    start = lines[0].start if char_start is None else char_start
    # Page offsets relative to the slice text: the text is the lines
    # joined by "\n", so a line's text offset is its canonical offset
    # minus the slice's char_start.
    page_offsets: List[Tuple[int, int]] = []
    last_page: Optional[int] = None
    for line in lines:
        if line.page is not None and line.page != last_page:
            page_offsets.append((line.start - start, line.page))
            last_page = line.page
    if text is None:
        text = _slice_text(lines)
        if lines and lines[-1].end_incl > lines[-1].end:
            text += "\n"  # this slice owns its trailing separator newline
    return DocumentSlice(
        slice_id=f"{doc_slug(doc_id)}-s{index:04d}",
        doc_id=doc_id,
        document_hint=document_hint,
        page_start=lines[0].page if lines else None,
        page_end=lines[-1].page if lines else None,
        heading=heading,
        char_start=start,
        char_end=lines[-1].end_incl if char_end is None else char_end,
        text=text,
        page_offsets=tuple(page_offsets),
    )


def _paragraph_split_index(
    lines: List[_Line], *, target_chars: int, max_chars: int
) -> Optional[int]:
    """Index of the blank line a size cut should land on, or None.

    Scans the group from the end for a blank (paragraph-break) line
    whose inclusive end lands within ``_PARAGRAPH_CUT_WINDOW`` chars
    of the target and never beyond ``max_chars``. The split keeps
    ``lines[:j + 1]`` (through the blank line) in the closing group,
    so the paragraph stays whole in one slice. Returns None when no
    paragraph break is in the window — the caller then defers the
    cut (forward window) or falls back to the first line boundary
    past the target, exactly as before this preference existed.
    """

    if len(lines) < 3:
        return None
    start = lines[0].start
    for j in range(len(lines) - 2, 0, -1):
        if lines[j].text.strip():
            continue
        prefix_span = lines[j].end_incl - start
        if prefix_span > max_chars:
            continue
        if prefix_span >= target_chars - _PARAGRAPH_CUT_WINDOW:
            return j
        # Prefixes only shrink from here; once below the window no
        # earlier blank line can qualify either.
        if prefix_span < target_chars - _PARAGRAPH_CUT_WINDOW:
            break
    return None


def build_document_map(
    *,
    doc_id: str,
    document_hint: str,
    pages: Iterable[str],
    object_path: Optional[str] = None,
    paged: bool = True,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> DocumentMap:
    """Partition a document (given as a page iterable) into slices.

    ``paged=False`` treats the input as page-less raw text: page fields on
    the resulting slices are ``None`` and citations fall back to character
    ranges (used by the ``*_from_text`` extractor entry points).
    """

    lines, page_count, total_chars = _iter_lines(pages, paged=paged)

    # --- group lines into raw slices (no overlap yet) ---------------------
    # Each group: (lines, heading, cut_reason) where cut_reason is
    # "heading" | "size" | "end" for the cut that ENDS the group.
    groups: List[Tuple[List[_Line], Optional[str], str]] = []
    current: List[_Line] = []
    current_heading: Optional[str] = None
    current_len = 0  # canonical chars covered, incl. internal newlines

    def _flush(reason: str) -> None:
        nonlocal current, current_heading, current_len
        if current:
            groups.append((current, current_heading, reason))
        current = []
        current_heading = None
        current_len = 0

    for line in lines:
        line_len = line.end - line.start
        is_heading = looks_like_heading(line.text)
        if (
            is_heading
            and current
            and current_len >= _HEADING_MIN_SLICE_CHARS
        ):
            _flush("heading")
        if not current:
            current_heading = line.text.strip() if is_heading else None
        # Hard cap: a single over-long line is split into max-sized pieces.
        if line_len > max_chars:
            if current:
                _flush("size")
            pos = line.start
            chunk_index = 0
            while pos < line.end:
                piece_end = min(pos + max_chars, line.end)
                piece = _Line(
                    text=line.text[pos - line.start : piece_end - line.start],
                    start=pos,
                    end=piece_end,
                    page=line.page,
                    end_incl=piece_end if piece_end < line.end else line.end_incl,
                )
                groups.append(
                    ([piece], line.text.strip() if chunk_index == 0 and is_heading else None, "size")
                )
                pos = piece_end
                chunk_index += 1
            continue
        # Size cut at a line boundary once the target is reached, and a
        # hard guarantee that no group spans more than max_chars. When
        # the cut is due but the hard cap is not at risk, a paragraph
        # boundary is preferred: land on a recent blank line
        # (look-back), or defer up to the window past the target
        # waiting for one (look-ahead), or — no break in the window —
        # cut at the line boundary exactly as before.
        if current:
            hard = (line.end_incl - current[0].start) > max_chars
            if current_len >= target_chars or hard:
                split_at = (
                    None
                    if hard
                    else _paragraph_split_index(
                        current, target_chars=target_chars, max_chars=max_chars
                    )
                )
                if split_at is not None:
                    groups.append(
                        (current[: split_at + 1], current_heading, "size")
                    )
                    current = current[split_at + 1 :]
                    current_heading = None  # continuation, not a new section
                    current_len = sum((l.end - l.start) + 1 for l in current)
                elif (
                    not hard
                    and (current[-1].end_incl - current[0].start)
                    < target_chars + _PARAGRAPH_CUT_WINDOW
                    and line.text.strip()
                ):
                    pass  # defer: a paragraph break may land in the window
                elif (
                    not hard
                    and not line.text.strip()
                    and (current[-1].end_incl - current[0].start)
                    < target_chars + _PARAGRAPH_CUT_WINDOW
                ):
                    # The incoming blank line closes the paragraph
                    # inside the window; it belongs to this group.
                    current.append(line)
                    current_len += line_len + 1
                    _flush("size")
                    continue
                else:
                    _flush("size")
                    current_heading = line.text.strip() if is_heading else None
        current.append(line)
        current_len += line_len + 1  # +1 for the joining newline (approx. at tail)
    _flush("end")

    # --- merge a too-small trailing group into its predecessor ------------
    if len(groups) >= 2:
        last_lines, last_heading, _ = groups[-1]
        last_span = last_lines[-1].end - last_lines[0].start
        prev_lines, prev_heading, _ = groups[-2]
        combined_span = last_lines[-1].end_incl - prev_lines[0].start
        if last_span < min_chars and combined_span <= max_chars:
            groups[-2] = (prev_lines + last_lines, prev_heading, "end")
            groups.pop()

    # --- materialise slices, applying overlap after size cuts -------------
    slices: List[DocumentSlice] = []
    prev_group_lines: Optional[List[_Line]] = None
    prev_cut_reason: Optional[str] = None
    for index, (group_lines, heading, cut_reason) in enumerate(groups):
        effective_lines = list(group_lines)
        if (
            prev_group_lines is not None
            and prev_cut_reason == "size"
            and overlap_chars > 0
        ):
            # Seed this slice with trailing whole lines of the previous
            # group (up to ~overlap_chars) so boundary-straddling facts
            # appear whole in at least one slice.
            seed: List[_Line] = []
            seed_len = 0
            for prev_line in reversed(prev_group_lines):
                plen = prev_line.end - prev_line.start
                if seed and seed_len + plen > overlap_chars:
                    break
                seed.insert(0, prev_line)
                seed_len += plen + 1
                if seed_len >= overlap_chars:
                    break
            # Boundedness wins over overlap: drop seed lines from the
            # front until the combined slice fits within max_chars.
            while (
                seed
                and effective_lines
                and (effective_lines[-1].end_incl - seed[0].start) > max_chars
            ):
                seed.pop(0)
            effective_lines = seed + effective_lines
        slices.append(
            _make_slice(
                index=len(slices),
                doc_id=doc_id,
                document_hint=document_hint,
                lines=effective_lines,
                heading=heading,
            )
        )
        prev_group_lines = group_lines
        prev_cut_reason = cut_reason

    return DocumentMap(
        doc_id=doc_id,
        document_hint=document_hint,
        object_path=object_path,
        page_count=page_count,
        total_chars=total_chars,
        slices=slices,
    )


def group_slices_for_dispatch(
    slices: List[DocumentSlice], *, char_budget: int
) -> List[List[DocumentSlice]]:
    """Group consecutive slices into dispatch units within a char budget.

    Every slice appears in exactly one unit; units preserve document
    order. A single slice larger than the budget forms its own unit.
    """

    units: List[List[DocumentSlice]] = []
    current: List[DocumentSlice] = []
    current_chars = 0
    for sl in slices:
        if current and current_chars + sl.char_count > char_budget:
            units.append(current)
            current = []
            current_chars = 0
        current.append(sl)
        current_chars += sl.char_count
    if current:
        units.append(current)
    return units


def coverage_gaps(
    slices: List[DocumentSlice], total_chars: int
) -> List[Tuple[int, int]]:
    """Return uncovered [start, end) ranges of the canonical text.

    An empty result means full coverage — the slicing invariant.
    """

    if total_chars <= 0:
        return []
    covered = sorted((s.char_start, s.char_end) for s in slices)
    gaps: List[Tuple[int, int]] = []
    cursor = 0
    for start, end in covered:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_chars:
        gaps.append((cursor, total_chars))
    return gaps
