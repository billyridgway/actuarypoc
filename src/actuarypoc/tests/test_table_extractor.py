from __future__ import annotations

"""Tests for the deterministic table channel (pdfplumber).

The acceptance property: the premium table in the long synthetic filing
is lifted cell-for-cell exactly, and ordinary prose pages yield no
tables (the line-less text strategy is gated so it cannot chop
paragraphs into fake columns).
"""

import importlib.util
from pathlib import Path

from actuarypoc.extract.table_extractor import extract_tables_from_pdf_bytes


def _load_generator():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "long_synthetic_filing", root / "examples" / "long_synthetic_filing.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load_generator()
GT = GEN.GROUND_TRUTH


def test_long_filing_table_is_cell_exact(tmp_path):
    path = tmp_path / "long.pdf"
    GEN.build(str(path))
    tables = extract_tables_from_pdf_bytes(
        path.read_bytes(), document="long-synthetic-filing.pdf", object_path="x/long.pdf"
    )
    assert len(tables) == 1
    table = tables[0]
    assert table["page"] == 33
    assert table["title"] == GT["table_title"]
    assert table["columns"] == GT["table_columns"]
    assert table["rows"] == GT["table_rows"]
    assert table["provenance"]["engine"] == "pdfplumber"


def test_prose_only_pdf_yields_no_tables():
    page = GEN._prose_page(
        "GENERAL PROVISIONS",
        [GEN._FILLER_PARAGRAPHS[0], GEN._FILLER_PARAGRAPHS[1]],
        "SYNTHETIC TEST FILING - NOT A REAL PRODUCT",
    )
    content = GEN.build_pdf_bytes([page])
    tables = extract_tables_from_pdf_bytes(content, document="prose.pdf")
    assert tables == []


def test_small_ruled_table_exact():
    page = GEN._Page()
    page.text(50, 748, "SAMPLE RATE TABLE")
    col_x = [50, 150, 300, 450]
    top, row_h = 700.0, 22.0
    rows = [["Band", "Rate A", "Rate B"], ["1", "0.10", "0.20"], ["2", "0.30", "0.40"]]
    bottom = top - row_h * len(rows)
    for i in range(len(rows) + 1):
        y = top - row_h * i
        page.line(col_x[0], y, col_x[-1], y)
    for x in col_x:
        page.line(x, bottom, x, top)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.text(col_x[c] + 4, top - row_h * r - 15, cell)
    content = GEN.build_pdf_bytes([page])
    tables = extract_tables_from_pdf_bytes(content, document="small.pdf")
    assert len(tables) == 1
    assert tables[0]["columns"] == ["Band", "Rate A", "Rate B"]
    assert tables[0]["rows"] == [["1", "0.10", "0.20"], ["2", "0.30", "0.40"]]
    assert tables[0]["title"] == "SAMPLE RATE TABLE"
    assert tables[0]["page"] == 1
