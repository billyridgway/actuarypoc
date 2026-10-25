from __future__ import annotations

"""Deterministic PDF table extraction (the "table channel").

Tables carry the numbers an illustration runs on, so they are lifted out
of the PDF as structured grids by pdfplumber — the model is never asked
to read a table and never transcribes a number (parse-don't-generate;
see ``docs/slice-extraction-plan.md`` §5).

Each extracted table becomes a plain-dict *table artifact* with page
provenance, the strategy that found it, and cell values exactly as the
PDF text layer carries them (stripped of surrounding whitespace only).
This channel makes no LLM calls.

It coexists with ``workspace_ul_mechanics`` (semantic UL schedule
extraction for the executable-mechanics path); this module is the
generic, provenance-first grid channel for arbitrary filed tables.
"""

import hashlib
import io
import re
from typing import Any, Dict, List, Optional, Tuple

# Strategies tried per page, in order; the first yielding >= 1 table wins
# for that page and is recorded in the artifact's provenance.
_STRATEGIES: List[Dict[str, Any]] = [
    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
    {"vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict"},
    {"vertical_strategy": "text", "horizontal_strategy": "text"},
]

_NUMERIC = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?%?$")


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _looks_numeric(cell: str) -> bool:
    return bool(_NUMERIC.match(cell or ""))


def _split_header(rows: List[List[str]]) -> tuple[List[str], List[List[str]]]:
    """Split a leading header row off when it looks like one.

    A row counts as a header when at least half of its non-empty cells
    are non-numeric. Data rows are returned untouched otherwise.
    """

    if not rows:
        return [], rows
    first = rows[0]
    non_empty = [c for c in first if c]
    if non_empty and sum(1 for c in non_empty if not _looks_numeric(c)) * 2 >= len(non_empty):
        return first, rows[1:]
    return [], rows


def _lines_above(page: Any, table_top: float) -> List[Tuple[float, str]]:
    """Text lines above ``table_top`` as (bottom, text), nearest last."""

    try:
        words = page.extract_words() or []
    except Exception:
        return []
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    bottoms: Dict[int, float] = {}
    for w in words:
        if float(w.get("bottom", 0)) <= table_top + 1:
            key = int(round(float(w.get("top", 0))))
            grouped.setdefault(key, []).append(w)
            bottoms[key] = max(bottoms.get(key, 0.0), float(w.get("bottom", 0)))
    out: List[Tuple[float, str]] = []
    for key in sorted(grouped.keys()):
        line_words = sorted(grouped[key], key=lambda w: float(w.get("x0", 0)))
        text = " ".join(str(w.get("text", "")) for w in line_words).strip()
        if text:
            out.append((bottoms[key], text))
    return out


def _title_above(page: Any, table_bbox: Any) -> Optional[str]:
    """Title for a table: the nearest heading-like line above it.

    Filed tables are captioned by a heading ("ANNUAL PREMIUM RATES …"),
    often with a prose subtitle between the caption and the grid, so a
    heading-like line within ~70pt wins over the merely-nearest line.
    """

    from actuarypoc.extract.document_map import looks_like_heading

    table_top = float(table_bbox[1]) if table_bbox else 0.0
    lines = _lines_above(page, table_top)
    if not lines:
        return None
    for bottom, text in reversed(lines):
        if table_top - bottom <= 70 and looks_like_heading(text):
            return text
    return lines[-1][1]


def _artifact_id(document: str, page: int, index: int, first_row: List[str]) -> str:
    basis = "|".join([document, str(page), str(index), " ".join(first_row)])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _plausible_grid(rows: List[List[str]]) -> bool:
    """Minimum shape for any accepted table: >=2 rows, >=2 columns."""

    return len(rows) >= 2 and max((len(r) for r in rows), default=0) >= 2


def _looks_like_data_grid(rows: List[List[str]]) -> bool:
    """Strict shape gate for tables found by the ``text`` strategy.

    Without ruling lines, pdfplumber's text strategy happily chops prose
    paragraphs into fake columns. A real borderless data table instead
    has a consistent column count and numeric cells arranged in at
    least one consistent column across most data rows.
    """

    if not _plausible_grid(rows):
        return False
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        return False
    ncols = widths.pop()
    data_rows = rows[1:] if len(rows) > 1 else rows
    if not data_rows:
        return False
    numeric_rows = 0
    numeric_cols: set = set()
    for row in data_rows:
        row_numeric = {i for i, c in enumerate(row) if _looks_numeric(c)}
        if row_numeric:
            numeric_rows += 1
            numeric_cols |= row_numeric
    if numeric_rows * 2 < len(data_rows):
        return False
    # Numerics must cluster in consistent columns, not scatter.
    return any(
        sum(1 for row in data_rows if _looks_numeric(row[c])) * 2 >= len(data_rows)
        for c in numeric_cols
    ) and ncols >= 2


def extract_tables_from_pdf_bytes(
    content: bytes,
    *,
    document: str,
    object_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract all tables from a PDF (given as bytes) as artifacts.

    Returns an empty list when the document has no detectable tables.
    Raises only on a fundamentally unreadable PDF; per-page strategy
    failures degrade to "no tables on that page".
    """

    import pdfplumber

    artifacts: List[Dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_no = page_index + 1
            # Try strategies in order; a strategy wins the page when at
            # least one of its tables passes the shape gate (the strict
            # data-grid gate for the line-less "text" strategy).
            accepted: List[Tuple[Any, List[List[str]]]] = []
            strategy_name = "lines"
            for settings in _STRATEGIES:
                strategy_name = str(settings["vertical_strategy"])
                try:
                    found = list(page.find_tables(table_settings=settings))
                except Exception:
                    found = []
                for table in found:
                    try:
                        raw_rows = table.extract() or []
                    except Exception:
                        continue
                    rows = [[_clean_cell(c) for c in row] for row in raw_rows]
                    rows = [r for r in rows if any(c for c in r)]
                    if strategy_name == "text":
                        if not _looks_like_data_grid(rows):
                            continue
                    elif not _plausible_grid(rows):
                        continue
                    accepted.append((table, rows))
                if accepted:
                    break
            for table_index, (table, rows) in enumerate(accepted):
                columns, data_rows = _split_header(rows)
                title = _title_above(page, getattr(table, "bbox", None))
                artifacts.append(
                    {
                        "id": _artifact_id(document, page_no, table_index, rows[0]),
                        "document": document,
                        "objectPath": object_path,
                        "page": page_no,
                        "indexOnPage": table_index,
                        "title": title,
                        "columns": columns,
                        "rows": data_rows,
                        "rowCount": len(data_rows),
                        "columnCount": max((len(r) for r in rows), default=0),
                        "provenance": {
                            "engine": "pdfplumber",
                            "strategy": strategy_name,
                        },
                    }
                )
    return artifacts
