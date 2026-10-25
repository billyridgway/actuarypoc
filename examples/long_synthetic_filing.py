"""Generate a LONG synthetic term-life filing PDF for extraction testing.

The document is >60,000 characters of extracted text. Its identity facts
(carrier, product name/code/type, filing reference), its issue-age range,
and its premium-rate table exist ONLY after character 50,000 of the
extracted text — the exact region the historical blob-and-truncate
extractors (``text[:50000]``) could never see. The premium table is a
properly ruled grid so deterministic table extraction (pdfplumber) can
lift it cell-for-cell.

Everything in the document is synthetic. Ground truth is in
``GROUND_TRUTH`` below.

Usage: python examples/long_synthetic_filing.py [output.pdf]
"""

from __future__ import annotations

import sys

GROUND_TRUTH = {
    "carrier": "Meridian Assurance Test Company",
    "product_name": "Synthetic Level Term 99",
    "product_code": "SYN-LT99",
    "product_type": "Level Term Life Insurance",
    "filing_id": "SYN-2026-099",
    "issue_ages": "21-60",
    "table_title": "ANNUAL PREMIUM RATES PER $1,000 OF FACE AMOUNT (SYNTHETIC)",
    "table_columns": [
        "Age",
        "Preferred Non-Tobacco",
        "Standard Non-Tobacco",
        "Standard Tobacco",
    ],
    "table_rows": [
        ["25", "1.31", "1.74", "2.66"],
        ["35", "1.52", "2.03", "3.18"],
        ["45", "2.87", "3.94", "6.22"],
        ["55", "6.85", "9.12", "14.57"],
        ["60", "11.40", "15.26", "24.83"],
    ],
}

# Filler paragraphs: generic provisions language. Deliberately contains
# NO carrier/product identity, NO "issue age(s)" phrasing, NO risk-class
# inventory, and NO form numbers — the late pages are the only source of
# those facts in this document.
_FILLER_PARAGRAPHS = [
    "The company will pay the death benefit to the beneficiary when it receives due proof of the death of the insured, provided the policy is in force on the date of death and all premiums then due have been paid in full.",
    "If a premium is not paid within the grace period allowed by this policy, the policy will lapse and all coverage will end, except as provided under any reinstatement provision that the company may later approve in writing.",
    "The owner may change the beneficiary at any time while the insured is living by filing a written request with the company at its home office, and any such change will take effect on the date the request is signed by the owner.",
    "This policy and the application together form the entire contract between the owner and the company, and no statement made by any person will bind the company unless it is included in the application and attached to the policy.",
    "The company may contest the validity of this policy on the ground of a material misrepresentation in the application during the first two years that the policy is in force, measured from the date of issue shown in the schedule.",
    "When the insured dies by suicide during the first two years after the date of issue, the amount payable will be limited to the premiums paid for this policy, less any indebtedness then owing to the company under the policy terms.",
    "If the age or sex of the insured has been misstated, the amount payable will be the amount that the premium paid would have purchased at the correct age or sex, according to the rates in effect on the date of issue.",
    "The owner may assign this policy as collateral security for a loan by filing a written assignment with the company, and the company will not be responsible for the validity or the sufficiency of any such assignment.",
    "Dividends are not guaranteed under this policy and no dividends will be paid or credited at any time, because this policy does not participate in the divisible surplus of the company in any year during its term.",
    "Settlement of the amount payable under this policy may be made in one sum or under one of the settlement options described in the policy, subject to the minimum amounts and the conditions stated in the policy provisions.",
    "The owner may request a loan or a partial withdrawal only to the extent that a cash surrender value has accumulated under this policy, and any such amount will reduce the death benefit and the cash value accordingly.",
    "Reports showing the current cash value, the outstanding indebtedness, and the premiums paid during the year will be provided to the owner at least once each year while this policy remains in force with the company.",
]


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, width: int = 86) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if len(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


class _Page:
    """One PDF page: positioned text lines plus optional ruled lines."""

    def __init__(self) -> None:
        self.texts: list[tuple[float, float, str]] = []  # (x, baseline_y, text)
        self.rules: list[tuple[float, float, float, float]] = []

    def text(self, x: float, y: float, s: str) -> None:
        self.texts.append((x, y, s))

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.rules.append((x1, y1, x2, y2))

    def stream(self) -> bytes:
        parts: list[str] = []
        for x, y, s in self.texts:
            parts.append(f"BT /F1 10 Tf {x:g} {y:g} Td ({_esc(s)}) Tj ET")
        if self.rules:
            parts.append("0.5 w")
            for x1, y1, x2, y2 in self.rules:
                parts.append(f"{x1:g} {y1:g} m {x2:g} {y2:g} l S")
        # Trailing newline inside the stream: some parsers (pdfminer)
        # drop a final path operator that ends exactly at stream end.
        return ("\n".join(parts) + "\n").encode("latin-1")


def _prose_page(heading: str, paragraphs: list[str], marker: str) -> _Page:
    page = _Page()
    y = 780.0
    page.text(50, y, marker)
    y -= 26
    page.text(50, y, heading)
    y -= 20
    for para in paragraphs:
        for line in _wrap(para):
            page.text(50, y, line)
            y -= 13
        y -= 10
    return page


def _filler_pages(count: int) -> list[_Page]:
    pages: list[_Page] = []
    idx = 0
    for n in range(count):
        paras = []
        chars = 0
        while chars < 1900:
            para = _FILLER_PARAGRAPHS[idx % len(_FILLER_PARAGRAPHS)]
            idx += 1
            paras.append(para)
            chars += len(para)
        heading = "GENERAL PROVISIONS" if n % 3 else "POLICY PROVISIONS CONTINUED"
        pages.append(
            _prose_page(heading, paras, "SYNTHETIC TEST FILING - NOT A REAL PRODUCT")
        )
    return pages


def _identity_page() -> _Page:
    page = _Page()
    y = 780.0
    page.text(50, y, "SYNTHETIC TEST FILING - NOT A REAL PRODUCT")
    y -= 26
    page.text(50, y, "CARRIER AND PRODUCT IDENTIFICATION")
    y -= 24
    lines = [
        "Carrier: Meridian Assurance Test Company (SYNTHETIC)",
        "Product name: Synthetic Level Term 99",
        "Product code: SYN-LT99",
        "Product type: Level Term Life Insurance",
        "Filing reference: SYN-2026-099 (synthetic filing)",
        "",
        "This filing is submitted by Meridian Assurance Test Company in",
        "support of the Synthetic Level Term 99 product, a level term life",
        "insurance policy with a ninety-nine year premium guarantee period",
        "as described in the actuarial memorandum accompanying this filing.",
        "The product code SYN-LT99 should be used in all references to this",
        "filing, and the filing reference for tracking purposes is",
        "SYN-2026-099.",
    ]
    for line in lines:
        page.text(50, y, line)
        y -= 16
    return page


def _eligibility_page() -> _Page:
    page = _Page()
    y = 780.0
    page.text(50, y, "SYNTHETIC TEST FILING - NOT A REAL PRODUCT")
    y -= 26
    page.text(50, y, "ELIGIBILITY AND ISSUE AGES")
    y -= 24
    lines = [
        "Issue ages: 21 to 60 (age nearest birthday).",
        "Face amount: minimum $100,000, maximum $2,000,000.",
        "Premium pattern: level premiums for the full ninety-nine year",
        "guarantee period described in the identification section.",
        "Free look period: the owner may return the policy within 20 days",
        "of delivery for a full refund of premiums paid.",
        "Conversion: the policy may be converted to a permanent plan",
        "offered by the company before the insured reaches attained age 60,",
        "without evidence of insurability, at rates for the attained age.",
    ]
    for line in lines:
        page.text(50, y, line)
        y -= 16
    return page


def _table_page() -> _Page:
    page = _Page()
    page.text(50, 780, "SYNTHETIC TEST FILING - NOT A REAL PRODUCT")
    page.text(50, 748, GROUND_TRUTH["table_title"])
    page.text(50, 730, "Level premium period rates, blended by sex, per policy schedule.")

    col_x = [50, 110, 260, 400, 540]
    top = 700.0
    row_h = 22.0
    all_rows = [GROUND_TRUTH["table_columns"]] + GROUND_TRUTH["table_rows"]
    bottom = top - row_h * len(all_rows)
    for i in range(len(all_rows) + 1):
        y = top - row_h * i
        page.line(col_x[0], y, col_x[-1], y)
    for x in col_x:
        page.line(x, bottom, x, top)
    for r, row in enumerate(all_rows):
        baseline = top - row_h * r - 15
        for c, cell in enumerate(row):
            page.text(col_x[c] + 4, baseline, cell)
    page.text(50, bottom - 24, "Rates are annual premiums per $1,000 of face amount.")
    page.text(50, bottom - 38, "The policy fee is included in the tabular premium.")
    return page


def _rider_page() -> _Page:
    page = _Page()
    y = 780.0
    page.text(50, y, "SYNTHETIC TEST FILING - NOT A REAL PRODUCT")
    y -= 26
    page.text(50, y, "OPTIONAL RIDERS")
    y -= 24
    lines = [
        "Terminal Illness Accelerated Benefit Rider: upon certification",
        "that the insured has a life expectancy of twelve months or less,",
        "the owner may elect to receive up to fifty percent of the death",
        "benefit as a lump sum, and the remaining death benefit is reduced",
        "by the amount accelerated plus an administrative charge.",
        "",
        "Waiver of Premium Rider: if the insured becomes totally disabled",
        "before attained age 60 and remains disabled for six consecutive",
        "months, premiums falling due during the disability are waived.",
    ]
    for line in lines:
        page.text(50, y, line)
        y -= 16
    return page


def build_pages(filler_count: int = 30) -> list[_Page]:
    return (
        _filler_pages(filler_count)
        + [_identity_page(), _eligibility_page(), _table_page(), _rider_page()]
    )


def build_pdf_bytes(pages: list[_Page]) -> bytes:
    """Assemble a complete PDF (bytes) from built pages."""

    objects: list[tuple[int, bytes]] = []
    kids: list[str] = []
    next_num = 4
    for page in pages:
        data = page.stream()
        page_num = next_num
        content_num = next_num + 1
        next_num += 2
        kids.append(f"{page_num} 0 R")
        objects.append(
            (
                content_num,
                b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream",
            )
        )
        objects.append(
            (
                page_num,
                (
                    f"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 2 0 R >> >> /Contents {content_num} 0 R >>"
                ).encode(),
            )
        )
    objects.append((1, b"<< /Type /Catalog /Pages 3 0 R >>"))
    objects.append((2, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    objects.append(
        (3, ("<< /Type /Pages /Kids [" + " ".join(kids) + f"] /Count {len(kids)} >>").encode())
    )
    objects.sort(key=lambda t: t[0])

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num, body in objects:
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    maxnum = max(offsets) + 1
    out += f"xref\n0 {maxnum}\n".encode()
    out += b"0000000000 65535 f \n"
    for n in range(1, maxnum):
        out += f"{offsets[n]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {maxnum} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def build(path: str, filler_count: int = 30) -> dict:
    pages = build_pages(filler_count)
    data = build_pdf_bytes(pages)
    with open(path, "wb") as f:
        f.write(data)
    return {"path": path, "bytes": len(data), "pages": len(pages)}


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/long-synthetic-filing.pdf"
    info = build(out_path)
    print(f"wrote {info['path']} {info['bytes']} bytes, {info['pages']} pages")
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(out_path)
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        print(f"extracted text: {len(text)} chars")
        for marker in (
            GROUND_TRUTH["carrier"],
            GROUND_TRUTH["product_code"],
            GROUND_TRUTH["filing_id"],
            GROUND_TRUTH["table_title"],
            "Terminal Illness Accelerated Benefit Rider",
        ):
            print(f"  offset of {marker!r}: {text.find(marker)}")
    except Exception as exc:  # noqa: BLE001
        print(f"(text check skipped: {exc})")
