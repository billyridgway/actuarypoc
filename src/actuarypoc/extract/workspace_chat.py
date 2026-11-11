"""Grounded workbench chat (Nov 5, 2026).

A chat scoped to one workspace and its presented projection.  It
answers questions about the product (from the filing documents) and
about the illustration (from the run's own ledger), under the same
doctrine as the rest of the product:

* The chat NEVER computes numbers.  Every figure in an answer is
  quoted from the typed tool layer below — ledger rows, table rows
  in force, scenario fields, filing text — and a deterministic
  grounding pass drops any sentence whose numbers the tools did not
  provide.
* Scenario-change questions are never answered with numbers.  They
  return a structured proposal the UI applies to the scenario form;
  the projection engine remains the only thing that produces a new
  ledger.
* "Not in the documents" is a first-class answer, in the product's
  three-state language: covered by the documents / stated but not
  extracted / not in the documents.  Absence is stated, never
  improvised around.

Architecture: a two-stage pipeline.  Stage 1 is a cheap intent
router/screen — deterministic keyword/pattern rules first, a small
model call only when the rules are ambiguous — classifying each
message into exactly one of filing_fact, model_fact,
ledger_explanation, scenario_change, product_overview, out_of_scope,
and extracting structured slots.  Stage 2 is the answering call,
which receives ONLY the grounded context the tool layer assembled
for that intent and must answer from it, with citations.

The tool layer is plain internal functions over data the server
already holds (workspace snapshot, executable-mechanics artifact,
document slices, document coverage) — deliberately NOT an MCP
server; there is no external consumer yet, and an adapter can wrap
these same functions later if one appears.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from actuarypoc.domain import equations as _eq
from actuarypoc.extract import workspace_equations as _ws_eq


# ---------------------------------------------------------------------------
# Intents and labels
# ---------------------------------------------------------------------------

INTENT_FILING_FACT = "filing_fact"
INTENT_MODEL_FACT = "model_fact"
INTENT_LEDGER = "ledger_explanation"
INTENT_SCENARIO_CHANGE = "scenario_change"
INTENT_PRODUCT_OVERVIEW = "product_overview"
INTENT_OUT_OF_SCOPE = "out_of_scope"

INTENTS = (
    INTENT_FILING_FACT,
    INTENT_MODEL_FACT,
    INTENT_LEDGER,
    INTENT_SCENARIO_CHANGE,
    INTENT_PRODUCT_OVERVIEW,
    INTENT_OUT_OF_SCOPE,
)

#: The small provenance label the UI shows per answer — where the
#: answer came from, in the workbench's provenance-first style.
INTENT_LABELS = {
    INTENT_FILING_FACT: "From the filing",
    INTENT_MODEL_FACT: "From the model in force",
    INTENT_LEDGER: "From the ledger",
    INTENT_SCENARIO_CHANGE: "Scenario change",
    INTENT_PRODUCT_OVERVIEW: "Product overview",
    INTENT_OUT_OF_SCOPE: "Out of scope",
}


# ---------------------------------------------------------------------------
# Workspace context + the typed tool layer
# ---------------------------------------------------------------------------


@dataclass
class ChatContext:
    """Everything the tool layer may read for one workspace.

    Built by the server endpoint from existing data paths only:
    the workspace snapshot (saved illustration), the
    executable-mechanics artifact, the document slices, and the
    document-coverage computation.  ``presented_run`` is the run the
    UI is currently presenting (a diagnostic run lives client-side);
    when present it supersedes the snapshot's saved illustration.
    """

    workspace_id: str
    snapshot: Mapping[str, Any] = field(default_factory=dict)
    artifact: Mapping[str, Any] = field(default_factory=dict)
    slices: Sequence[Mapping[str, Any]] = field(default_factory=list)
    coverage: Mapping[str, Any] = field(default_factory=dict)
    presented_run: Optional[Mapping[str, Any]] = None

    # -- run access ----------------------------------------------------

    def _run(self) -> Mapping[str, Any]:
        if isinstance(self.presented_run, Mapping) and self.presented_run:
            return self.presented_run
        illustration = (self.snapshot or {}).get("illustration")
        return illustration if isinstance(illustration, Mapping) else {}

    @property
    def has_run(self) -> bool:
        return bool(self.run_rows())

    @property
    def has_filings(self) -> bool:
        return bool(self.slices)

    def run_rows(self) -> List[Dict[str, Any]]:
        run = self._run()
        rows = run.get("rows")
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
        ledger = run.get("ledger")
        if isinstance(ledger, Mapping):
            ledger_rows = ledger.get("rows")
            if isinstance(ledger_rows, list):
                return [r for r in ledger_rows if isinstance(r, dict)]
        return []

    # -- tools -----------------------------------------------------------

    def get_scenario(self) -> Optional[Dict[str, Any]]:
        """The scenario behind the presented run (tool-provided).

        The projection's normalised request echo carries most
        fields but NOT the modal premium — the engine consumes it
        without echoing it — so a missing premium (and a missing
        issue age) is recovered from the presented ledger itself:
        the first row's modal premium, and its attained age less
        the elapsed durations.  Both are figures the run itself
        produced, quoted — never derived by the chat.  Returns None
        when no scenario field is known at all (the analysis-time
        request carries mechanics only, no scenario)."""

        run = self._run()
        request = run.get("request")
        if not isinstance(request, Mapping):
            request = {}
        scenario: Dict[str, Any] = {
            "issue_age": request.get("age"),
            "face_amount": request.get("faceAmount"),
            "premium": request.get("modalPremium"),
            "premium_mode": request.get("premiumMode"),
            "sex": request.get("sex"),
            "risk_class": request.get("riskClass"),
            "tobacco_status": request.get("tobaccoStatus"),
        }
        if scenario["premium"] is None or scenario["issue_age"] is None:
            rows = self.run_rows()
            if rows:
                first = rows[0]
                if scenario["premium"] is None:
                    scenario["premium"] = first.get("modalPremium")
                    if scenario["premium"] is None:
                        scenario["premium"] = first.get("annualPremium")
                if scenario["issue_age"] is None:
                    attained = first.get("attainedAge")
                    year = first.get("year")
                    if isinstance(attained, (int, float)) and isinstance(
                        year, (int, float)
                    ):
                        scenario["issue_age"] = attained - (year - 1)
        if all(value is None for value in scenario.values()):
            return None
        return scenario

    def get_run_ledger(
        self, years: Optional[Sequence[int]] = None
    ) -> List[Dict[str, Any]]:
        """Presented projection rows, optionally windowed to years.

        Only the auditable columns travel — the chat quotes figures,
        it does not re-derive them.
        """

        rows = self.run_rows()
        if years:
            wanted = set()
            for year in years:
                wanted.update({year - 1, year, year + 1})
            rows = [
                r for r in rows
                if isinstance(r.get("year"), int) and r["year"] in wanted
            ]
        return [_ledger_row_view(r) for r in rows]

    def get_equation_in_force(self, mechanic: str) -> Optional[Dict[str, Any]]:
        """The in-force equation record for a mechanic, or None."""

        record = _ws_eq.in_force(self.artifact, mechanic)
        if record is None:
            return None
        source = record.get("source") or {}
        return {
            "mechanic": mechanic,
            "label": _eq.MECHANIC_LABELS.get(mechanic, mechanic),
            "statement": source.get("statement"),
            "sourceKind": source.get("kind"),
            "filename": source.get("filename"),
            "page": source.get("page"),
            "timing": _eq.timing_sentence(record.get("timing")),
            "body": record.get("body"),
        }

    def get_table_slice(
        self,
        table: str,
        selectors: Optional[Mapping[str, Any]] = None,
        limit: int = 25,
    ) -> Dict[str, Any]:
        """Rows of a table in force, filtered by selectors.

        A row whose selector field is null applies to every value of
        that selector (the surrender schedule's shape), so it matches
        any requested value; a row with a concrete value must equal
        the request.
        """

        if table not in _eq.TABLES:
            return {"table": table, "rows": [], "rowCount": 0, "inForce": False}
        key = _eq.TABLES[table][0]
        all_rows = [
            r for r in ((self.artifact.get("usable") or {}).get(key) or [])
            if isinstance(r, dict)
        ]
        selectors = dict(selectors or {})
        matched = [r for r in all_rows if _row_matches(r, selectors)]
        provenance = None
        if matched:
            prov = matched[0].get("provenance") or {}
            provenance = {
                "filename": prov.get("filename"),
                "page": prov.get("page"),
            }
        return {
            "table": table,
            "label": _eq.TABLE_LABELS.get(table, table),
            "inForce": bool(all_rows),
            "rowCount": len(matched),
            "totalRowsInForce": len(all_rows),
            "selectors": selectors,
            "provenance": provenance,
            "rows": matched[:limit],
            "truncated": len(matched) > limit,
        }

    def search_filing_text(
        self,
        query_terms: Sequence[str],
        limit: int = 5,
        topic_terms: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword search over the workspace's filing slices.

        Hits carry document + page provenance; the page is anchored
        through the slice's page offsets, so a citation names the
        page the matched text actually sits on.

        When ``topic_terms`` is given, each hit is also flagged
        ``topical``: the matched segment speaks to the question's
        actual topic (it contains at least one topic term), as
        opposed to matching only the question's generic framing
        vocabulary ("what does the filing say…"), which matches
        nearly every page of a filing.  The absence path keys on
        this flag: generic hits are not coverage."""

        terms = [t.lower() for t in query_terms if len(t) >= 3]
        if not terms:
            return []
        topics = [t.lower() for t in (topic_terms or []) if len(t) >= 3]
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for sl in self.slices:
            text = str(sl.get("text") or "")
            if not text:
                continue
            for segment, page in _page_segments(sl):
                lowered = segment.lower()
                score = sum(lowered.count(t) for t in terms)
                if score <= 0:
                    continue
                first = min(
                    (lowered.find(t) for t in terms if t in lowered),
                    default=0,
                )
                start = max(0, first - 240)
                end = min(len(segment), first + 420)
                snippet = segment[start:end].strip()
                if start > 0:
                    snippet = "…" + snippet
                if end < len(segment):
                    snippet = snippet + "…"
                scored.append((score, {
                    "document": sl.get("document_hint") or sl.get("doc_id"),
                    "page": page if page is not None else sl.get("page_start"),
                    "heading": sl.get("heading"),
                    "snippet": snippet,
                    "score": score,
                    "topical": (
                        not topics
                        or any(t in lowered for t in topics)
                    ),
                }))
        scored.sort(key=lambda item: -item[0])
        return [hit for _score, hit in scored[:limit]]

    def get_coverage_states(self) -> Dict[str, Any]:
        """The three-state document coverage, per mechanic + table."""

        equations = {}
        for mechanic, entry in ((self.coverage or {}).get("equations") or {}).items():
            equations[mechanic] = {
                "state": (entry or {}).get("state") or "absent",
                "filename": (entry or {}).get("filename"),
                "page": (entry or {}).get("page"),
                "statement": (entry or {}).get("statement"),
            }
        return {
            "equations": equations,
            "tables": dict((self.coverage or {}).get("tables") or {}),
        }


_LEDGER_COLUMNS = (
    "year", "attainedAge", "modalPremium", "annualPremium",
    "cumulativePremium", "premiumLoad", "guaranteedInterest",
    "coiCharge", "policyFee", "endingPolicyValue", "cashValue",
    "surrenderCharge", "surrenderValue", "deathBenefit",
    "netAmountAtRisk", "status",
)


def _ledger_row_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in _LEDGER_COLUMNS if key in row}


def _row_matches(row: Mapping[str, Any], selectors: Mapping[str, Any]) -> bool:
    for field_name, wanted in selectors.items():
        if wanted is None:
            continue
        actual = row.get(field_name)
        if actual is None:
            continue  # a null selector applies to every value
        if isinstance(actual, str) and isinstance(wanted, str):
            if actual.strip().lower() != wanted.strip().lower():
                return False
        elif actual != wanted:
            return False
    return True


def _page_segments(sl: Mapping[str, Any]) -> List[Tuple[str, Optional[int]]]:
    """Split a slice's text into (segment, page) via its page offsets."""

    text = str(sl.get("text") or "")
    offsets = sl.get("page_offsets") or []
    points: List[Tuple[int, Optional[int]]] = []
    for entry in offsets:
        try:
            points.append((int(entry[0]), int(entry[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if not points:
        return [(text, sl.get("page_start"))]
    points.sort()
    segments: List[Tuple[str, Optional[int]]] = []
    for index, (start, page) in enumerate(points):
        end = points[index + 1][0] if index + 1 < len(points) else len(text)
        if end > start:
            segments.append((text[start:end], page))
    return segments or [(text, sl.get("page_start"))]


# ---------------------------------------------------------------------------
# Stage 1: the intent router / screen
# ---------------------------------------------------------------------------

#: Mechanic keyword map (phrase -> mechanic).  Order matters: the
#: first matching mechanic wins for the primary slot, all matches are
#: kept in ``mechanics``.
_MECHANIC_PHRASES: Sequence[Tuple[str, str]] = (
    ("net amount at risk", "nar_definition"),
    ("amount at risk", "nar_definition"),
    ("nar definition", "nar_definition"),
    ("nar", "nar_definition"),
    ("cost of insurance", "coi_charge"),
    ("coi charge", "coi_charge"),
    ("coi", "coi_charge"),
    ("surrender charge", "surrender_charge"),
    ("surrender", "surrender_charge"),
    ("premium load", "premium_load"),
    ("expense charge", "premium_load"),
    ("policy fee", "policy_fees"),
    ("admin fee", "policy_fees"),
    ("administrative fee", "policy_fees"),
    ("policy fees", "policy_fees"),
    ("fees", "policy_fees"),
    ("crediting", "crediting"),
    ("credited interest", "crediting"),
    ("interest credited", "crediting"),
    ("death benefit", "death_benefit"),
)

#: Table keyword map (phrase -> table name in ``_eq.TABLES``).
_TABLE_PHRASES: Sequence[Tuple[str, str]] = (
    ("coi table", "coi"),
    ("coi rate", "coi"),
    ("surrender schedule", "surrender"),
    ("surrender table", "surrender"),
    ("fee schedule", "fees"),
    ("fees table", "fees"),
    ("nar factor", "nar_factors"),
    ("corridor", "corridor"),
)

_SCENARIO_SIGNALS: Sequence[str] = (
    "what if", "what happens if", "suppose", "instead of",
    "change the", "changed to", "increase", "decrease", "raise",
    "lower", "run with", "run it with", "if the premium",
    "if we", "if i", "were $", "was $",
)

_FILING_SIGNALS: Sequence[str] = (
    "filing", "in the documents", "policy form", "specimen",
    "what does the filing", "filing say", "filing state",
    "document say", "documents say", "stated in",
)

#: Product-feature nouns that, with no stronger anchor, make a
#: question a filing question (answerable only from the documents).
_FILING_FEATURE_PHRASES: Sequence[str] = (
    "grace period", "free look", "loan", "partial withdrawal",
    "withdrawal", "rider", "exclusion", "contestab", "suicide",
    "reinstat", "conversion", "dividend", "guarantee",
)

_ARITHMETIC_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|percent)\s+of\b)"
    r"|(\bcalculate\b|\bcompute\b|\bmultiply\b|\bdivide\b|\badd up\b"
    r"|\bsum of\b|\bhow much is\b|\btotal of\b)",
    re.IGNORECASE,
)

#: Product-overview anchor: a summary verb (summarize / describe /
#: overview / story / tell me about / what is this) aimed at the
#: product AS A WHOLE.  It is checked only after every specific
#: anchor (scenario, filing signal, ledger column, named mechanic
#: or table, filing feature), so "explain the COI charge" still
#: routes to the mechanic and "summarize the surrender table" to
#: the table — the overview fires only when nothing more specific
#: claimed the question.
_OVERVIEW_RE = re.compile(
    r"\b(?:summar\w+|overview|describe|description|story)\b"
    r"[^.?!]{0,60}?\b(?:product|policy|insurance|plan|coverage|this)\b"
    r"|\bexplain\b[^.?!]{0,40}?\b(?:product|policy|insurance|plan|this)\b"
    r"|\btell (?:me|us)\b[^.?!]{0,40}?"
    r"\b(?:product|policy|insurance|plan|coverage|story|this)\b"
    r"|\bwhat (?:is|kind of)\b[^.?!]{0,40}?"
    r"\b(?:product|policy|insurance|plan|this)\b"
    r"|\boverview of\b",
    re.IGNORECASE,
)


def _extract_mechanics(text: str) -> List[str]:
    found: List[str] = []
    for phrase, mechanic in _MECHANIC_PHRASES:
        if phrase in text and mechanic not in found:
            found.append(mechanic)
    return found


def _extract_tables(text: str) -> List[str]:
    found: List[str] = []
    for phrase, table in _TABLE_PHRASES:
        if phrase in text and table not in found:
            found.append(table)
    return found


def _extract_years(text: str) -> List[int]:
    years: List[int] = []
    for match in re.finditer(r"\b(?:policy\s+)?years?\s+(\d{1,3})\b", text):
        years.append(int(match.group(1)))
    for match in re.finditer(r"\byears?\s*[-–]\s*(\d{1,3})\b", text):
        years.append(int(match.group(1)))
    for match in re.finditer(r"\bduration\s+(\d{1,3})\b", text):
        years.append(int(match.group(1)))
    for match in re.finditer(r"\byears?\s+(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\b", text):
        lo, hi = int(match.group(1)), int(match.group(2))
        if hi >= lo and hi - lo <= 10:
            years.extend(range(lo, hi + 1))
    return sorted(set(years))


def _extract_age(text: str) -> Optional[int]:
    match = re.search(r"\bage\s+(\d{1,3})\b", text)
    return int(match.group(1)) if match else None


def _money_after(text: str, *anchors: str) -> Optional[float]:
    for anchor in anchors:
        match = re.search(
            anchor + r"[^$0-9]{0,24}\$?\s*([0-9][0-9,]*\.?[0-9]*)",
            text,
        )
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _extract_scenario_changes(text: str) -> List[Dict[str, Any]]:
    """Parse named scenario field changes out of a scenario message.

    Field names are the workbench scenario form's input ids, so the
    UI can apply a proposal without a translation layer.
    """

    changes: List[Dict[str, Any]] = []

    def add(field_name: str, label: str, value: Any) -> None:
        if value is None:
            return
        if any(c["field"] == field_name for c in changes):
            return
        changes.append({"field": field_name, "label": label, "newValue": value})

    premium = _money_after(text, r"premium", r"pay(?:ing|s|ment)?")
    add("premium", "Premium", premium)
    face = _money_after(text, r"face amount", r"face")
    add("face_amount", "Face amount", face)
    age = None
    age_match = re.search(r"(?:issue age|issued at|age)\s+(?:of\s+)?(\d{1,3})\b", text)
    if age_match:
        age = int(age_match.group(1))
    add("issue_age", "Issue age", age)
    for mode, label in (
        ("SEMIANNUAL", "semiannual"), ("QUARTERLY", "quarterly"),
        ("MONTHLY", "monthly"), ("ANNUAL", "annual"),
    ):
        if label in text:
            add("premium_mode", "Premium mode", mode)
            break
    if re.search(r"\bmale\b", text):
        add("sex", "Sex", "M")
    elif re.search(r"\bfemale\b", text):
        add("sex", "Sex", "F")
    if "non-tobacco" in text or "nontobacco" in text or "non tobacco" in text:
        add("tobacco_status", "Tobacco status", "Non-Tobacco")
    elif "tobacco" in text or "nicotine" in text or "smoker" in text:
        add("tobacco_status", "Tobacco status", "Tobacco")
    for risk in ("preferred", "standard", "substandard"):
        if risk in text:
            add("risk_class", "Risk class", risk.capitalize())
            break
    return changes


@dataclass
class Route:
    intent: str
    slots: Dict[str, Any]
    ambiguous: bool = False


def classify_intent_rules(message: str) -> Route:
    """Deterministic first pass of the router.

    Returns a Route; ``ambiguous`` is set when no rule anchored the
    message strongly, in which case the orchestrator may ask the
    small router model (when one is configured) to classify.
    """

    text = f" {(message or '').lower()} "
    mechanics = _extract_mechanics(text)
    tables = _extract_tables(text)
    years = _extract_years(text)
    slots: Dict[str, Any] = {
        "mechanics": mechanics,
        "tables": tables,
        "years": years,
        "age": _extract_age(text),
        "arithmetic_request": bool(_ARITHMETIC_RE.search(message or "")),
    }

    # Scenario change: an explicit hypothetical/change signal, with
    # at least one parseable field change — a hypothetical about
    # mechanics ("what if the COI doubled") carries no field change
    # and is NOT routable to the scenario form; it falls through and
    # is answered (as an explanation of what drives the number) or
    # screened by the model pass.
    changes = _extract_scenario_changes(text)
    if changes and any(signal in text for signal in _SCENARIO_SIGNALS):
        slots["scenario_changes"] = changes
        return Route(INTENT_SCENARIO_CHANGE, slots)
    if changes and re.search(r"\bchange\b|\bset\b", text):
        slots["scenario_changes"] = changes
        return Route(INTENT_SCENARIO_CHANGE, slots)

    # Explicit filing reference beats the mechanic anchor: "what does
    # the filing say about the COI charge" is a filing question.
    if any(signal in text for signal in _FILING_SIGNALS):
        return Route(INTENT_FILING_FACT, slots)

    # Ledger anchor: a ledger column phrase, or a year/duration
    # reference with no filed table in play ("what happens in year
    # 20").  A named table re-points duration references at the
    # table's rows instead ("COI rate at duration 5" is model_fact).
    _STRONG_LEDGER = (
        "cash value", "surrender value", "account value", "policy value",
        "ledger", "projection", "illustration", "ending value",
        "cumulative premium", "year by year",
    )
    if any(phrase in text for phrase in _STRONG_LEDGER) or (years and not tables):
        return Route(INTENT_LEDGER, slots)

    # Model anchor: a named mechanic or filed table.
    if mechanics or tables:
        return Route(INTENT_MODEL_FACT, slots)

    # Filing-feature anchor: product features that only the documents
    # can speak to.
    if any(phrase in text for phrase in _FILING_FEATURE_PHRASES):
        return Route(INTENT_FILING_FACT, slots)

    # Product-overview anchor: a summary of the product as a whole.
    # Last before the fallthrough — every specific anchor above has
    # already had its claim on the question.
    if _OVERVIEW_RE.search(message or ""):
        return Route(INTENT_PRODUCT_OVERVIEW, slots)

    return Route(INTENT_OUT_OF_SCOPE, slots, ambiguous=True)


_ROUTER_SYSTEM_PROMPT = (
    "You classify one question asked inside an actuarial workbench "
    "about a single life insurance product and its presented "
    "illustration. Output valid JSON only: {\"intent\": one of "
    "[\"filing_fact\", \"model_fact\", \"ledger_explanation\", "
    "\"scenario_change\", \"product_overview\", \"out_of_scope\"], "
    "\"mechanics\": [mechanic ids], \"years\": [ints], \"tables\": "
    "[table names]}. "
    "filing_fact = what the filed documents say; model_fact = the "
    "equations/tables in force and how a mechanic is defined; "
    "ledger_explanation = why the presented projection's numbers are "
    "what they are; scenario_change = the user wants different "
    "scenario inputs run; product_overview = the user wants a "
    "summary or overview of the product as a whole — what it is, "
    "its story — not one mechanic, table, or figure; "
    "out_of_scope = anything else. Mechanic "
    "ids: coi_charge, surrender_charge, premium_load, policy_fees, "
    "crediting, nar_definition, death_benefit. Tables: coi, "
    "surrender, fees, nar_factors, corridor."
)


def classify_intent(
    message: str,
    router_caller: Optional[Callable[[str, str], Any]] = None,
) -> Route:
    """Rules first; the model pass runs only on an ambiguous rules
    result, and only when a caller is configured.  A model result is
    accepted only if it names a valid intent — otherwise the rules
    result stands."""

    route = classify_intent_rules(message)
    if not route.ambiguous or router_caller is None:
        return route
    try:
        payload = router_caller(_ROUTER_SYSTEM_PROMPT, message)
    except Exception:  # noqa: BLE001 - the rules result stands
        return route
    if not isinstance(payload, dict):
        return route
    intent = payload.get("intent")
    if intent not in INTENTS:
        return route
    slots = dict(route.slots)
    for key in ("mechanics", "tables"):
        values = payload.get(key)
        if isinstance(values, list):
            slots[key] = [str(v) for v in values]
    years = payload.get("years")
    if isinstance(years, list):
        slots["years"] = sorted({int(y) for y in years if isinstance(y, int)})
    if intent == INTENT_SCENARIO_CHANGE:
        changes = _extract_scenario_changes(f" {(message or '').lower()} ")
        if changes:
            slots["scenario_changes"] = changes
        else:
            intent = INTENT_LEDGER if slots["years"] else INTENT_MODEL_FACT
    return Route(intent, slots)


# ---------------------------------------------------------------------------
# Grounded context assembly (per intent)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "what", "does", "the", "this", "that", "with", "from", "about",
    "which", "when", "where", "there", "their", "would", "could",
    "should", "into", "have", "been", "were", "will", "your",
    "product", "policy", "please", "tell", "show", "give", "much",
    "many", "mean", "means", "happen", "happens",
}

#: Extra search synonyms so a question's vocabulary reaches the
#: filing's vocabulary.
_SYNONYMS: Dict[str, Sequence[str]] = {
    "nar_definition": ("net amount at risk", "amount at risk"),
    "coi_charge": ("cost of insurance",),
    "surrender_charge": ("surrender charge", "surrender"),
    "premium_load": ("premium expense charge", "load"),
    "policy_fees": ("policy fee", "administrative charge"),
    "crediting": ("credited interest", "crediting"),
    "death_benefit": ("death benefit",),
}


def _query_terms(message: str, slots: Mapping[str, Any]) -> List[str]:
    terms: List[str] = []
    for mechanic in slots.get("mechanics") or []:
        terms.extend(_SYNONYMS.get(mechanic, ()))
        terms.append(_eq.MECHANIC_LABELS.get(mechanic, mechanic))
    for table in slots.get("tables") or []:
        terms.append(_eq.TABLE_LABELS.get(table, table))
    for word in re.findall(r"[a-z][a-z\-]{2,}", (message or "").lower()):
        if word not in _STOPWORDS and word not in terms:
            terms.append(word)
    return terms


#: Single words that match filing text regardless of the question's
#: topic — the question's framing vocabulary ("what does the filing
#: say") and the filing's own ubiquitous vocabulary ("policy",
#: "benefit", "premium").  A search hit matching ONLY these is not
#: coverage of the topic asked about.  Multiword terms (the filed
#: phrases: "net amount at risk", "surrender charge") are never
#: generic — a segment containing one speaks to the topic.
_GENERIC_TOPIC_WORDS = {
    "filing", "filings", "document", "documents", "say", "says",
    "said", "state", "states", "stated", "mention", "mentions",
    "mentioned", "allow", "allows", "allowed", "provide", "provides",
    "provided", "cover", "covers", "covered", "include", "includes",
    "included", "benefit", "benefits", "policy", "product",
    "coverage", "premium", "premiums", "charge", "charges", "value",
    "values", "account", "death", "insurance", "life", "term",
    "period", "amount", "amounts", "payment", "payments",
    "policyholder", "insured", "owner", "company", "plan", "rate",
    "rates", "cost", "fee", "fees", "year", "years", "contract",
    "interest",
}


def _distinctive_terms(terms: Sequence[str]) -> List[str]:
    """The terms that carry the question's topic: every multiword
    phrase, plus single words outside the generic vocabulary."""

    return [
        t for t in terms
        if " " in t or t.lower() not in _GENERIC_TOPIC_WORDS
    ]


#: Broad product vocabulary for the overview's framing search: the
#: passages that describe the product as a whole (actuarial-memo
#: introductions, the policy form's framing pages) are dense in it.
_OVERVIEW_SEARCH_TERMS: Sequence[str] = (
    "universal life", "flexible premium", "adjustable life",
    "life insurance", "death benefit", "cash value", "policy value",
    "premium", "policy", "insurance", "coverage",
)

#: Ledger columns that hold money.  In the stage-2 context they are
#: rendered as currency ("$53,515.47") rather than raw floats
#: (53515.465876699025): the value quoted is the ledger value,
#: rounded for display by the tool layer — the chat quotes figures
#: the way the workbench prints them, and the grounding pass checks
#: answers against these same rendered figures.
_LEDGER_MONEY_COLUMNS = (
    "modalPremium", "annualPremium", "cumulativePremium",
    "premiumLoad", "guaranteedInterest", "coiCharge", "policyFee",
    "endingPolicyValue", "cashValue", "surrenderCharge",
    "surrenderValue", "deathBenefit", "netAmountAtRisk",
)


def _ledger_row_display(row: Mapping[str, Any]) -> Dict[str, Any]:
    """A ledger row for the answering context: money as currency,
    everything else (year, attained age, status) untouched."""

    out: Dict[str, Any] = {}
    for key, value in row.items():
        if key in _LEDGER_MONEY_COLUMNS and isinstance(value, (int, float)):
            out[key] = _fmt_money(value)
        else:
            out[key] = value
    return out


def _table_selectors(slots: Mapping[str, Any]) -> Dict[str, Any]:
    selectors: Dict[str, Any] = {}
    years = slots.get("years") or []
    if years:
        selectors["duration"] = years[0]
    if slots.get("age") is not None:
        selectors["attained_age"] = slots["age"]
    return selectors


def assemble_context(
    ctx: ChatContext, route: Route, message: str
) -> Dict[str, Any]:
    """The ONLY material stage 2 may answer from, per intent."""

    slots = route.slots
    payload: Dict[str, Any] = {"intent": route.intent}
    if route.intent == INTENT_FILING_FACT:
        terms = _query_terms(message, slots)
        payload["filing_hits"] = ctx.search_filing_text(
            terms, topic_terms=_distinctive_terms(terms)
        )
        payload["coverage"] = ctx.get_coverage_states()
    elif route.intent == INTENT_MODEL_FACT:
        equations: Dict[str, Any] = {}
        for mechanic in slots.get("mechanics") or []:
            equations[mechanic] = ctx.get_equation_in_force(mechanic)
        payload["equations_in_force"] = equations
        tables: Dict[str, Any] = {}
        for table in slots.get("tables") or []:
            tables[table] = ctx.get_table_slice(
                table, _table_selectors(slots)
            )
        payload["tables_in_force"] = tables
        payload["coverage"] = ctx.get_coverage_states()
    elif route.intent == INTENT_LEDGER:
        payload["scenario"] = ctx.get_scenario()
        payload["ledger_rows"] = [
            _ledger_row_display(row)
            for row in ctx.get_run_ledger(slots.get("years") or None)
        ]
        payload["has_run"] = ctx.has_run
        # The definitions behind the numbers are ledger context too:
        # "why" questions are usually definition questions in disguise.
        equations = {}
        for mechanic in slots.get("mechanics") or []:
            equations[mechanic] = ctx.get_equation_in_force(mechanic)
        if equations:
            payload["equations_in_force"] = equations
    elif route.intent == INTENT_PRODUCT_OVERVIEW:
        # The product as a whole: the filings' framing passages,
        # the document inventory, the mechanics and tables in force
        # (names + filed statements), and the presented scenario.
        payload["filing_hits"] = ctx.search_filing_text(
            _OVERVIEW_SEARCH_TERMS, limit=6
        )
        payload["documents"] = sorted({
            str(sl.get("document_hint") or sl.get("doc_id"))
            for sl in ctx.slices
            if sl.get("document_hint") or sl.get("doc_id")
        })
        equations = {}
        for mechanic in _eq.MECHANICS:
            record = ctx.get_equation_in_force(mechanic)
            if record:
                equations[mechanic] = record
        payload["equations_in_force"] = equations
        tables = {}
        for table in _eq.TABLES:
            view = ctx.get_table_slice(table, limit=0)
            if view.get("inForce"):
                tables[table] = {
                    key: value for key, value in view.items()
                    if key != "rows"
                }
        payload["tables_in_force"] = tables
        payload["scenario"] = ctx.get_scenario()
        product = (ctx.snapshot or {}).get("product") or {}
        payload["product"] = {
            key: product.get(key)
            for key in ("code", "name", "type")
            if product.get(key)
        }
        payload["has_filings"] = ctx.has_filings
    return payload


# ---------------------------------------------------------------------------
# Grounding: numbers and citations may only come from the tools
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\$?\d[\d,]*\.?\d*\s?%?")


def _numbers_in(text: str) -> List[float]:
    values: List[float] = []
    for match in _NUMBER_RE.finditer(text or ""):
        token = match.group(0).replace("$", "").replace(",", "").strip()
        is_percent = token.endswith("%")
        token = token.rstrip("%").strip()
        try:
            value = float(token)
        except ValueError:
            continue
        values.append(value)
        if is_percent:
            values.append(value / 100.0)
    return values


def _grounded_numbers(
    payload: Mapping[str, Any], message: str
) -> List[float]:
    """Every number the tools provided (plus the user's own figures,
    which an answer may quote back)."""

    values = _numbers_in(json.dumps(payload, default=str))
    values.extend(_numbers_in(message or ""))
    return values


def _number_grounded(value: float, grounded: Sequence[float]) -> bool:
    for candidate in grounded:
        if abs(value - candidate) <= max(0.011, abs(candidate) * 0.001):
            return True
    return False


def ungrounded_numbers(
    answer: str, payload: Mapping[str, Any], message: str
) -> List[float]:
    grounded = _grounded_numbers(payload, message)
    return [
        value for value in _numbers_in(answer)
        if not _number_grounded(value, grounded)
    ]


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [part for part in parts if part]


def enforce_grounding(
    answer: str, payload: Mapping[str, Any], message: str
) -> Tuple[str, bool]:
    """Drop any sentence carrying a number the tools did not give.

    Returns (answer, discarded) — discarded is True when at least
    one sentence was dropped, so the response can disclose it.
    """

    grounded = _grounded_numbers(payload, message)
    kept: List[str] = []
    discarded = False
    for sentence in _sentences(answer):
        bad = [
            value for value in _numbers_in(sentence)
            if not _number_grounded(value, grounded)
        ]
        if bad:
            discarded = True
            continue
        kept.append(sentence)
    return " ".join(kept).strip(), discarded


def validate_citations(
    raw: Any, payload: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Keep only citations that name material the tools provided."""

    if not isinstance(raw, list):
        return []
    filing_keys = {
        (str(hit.get("document")), hit.get("page"))
        for hit in payload.get("filing_hits") or []
    }
    equation_mechanics = {
        mechanic
        for mechanic, record in (payload.get("equations_in_force") or {}).items()
        if record
    }
    table_names = {
        table
        for table, view in (payload.get("tables_in_force") or {}).items()
        if view and view.get("inForce")
    }
    ledger_years = {
        row.get("year") for row in payload.get("ledger_rows") or []
    }
    citations: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "filing":
            key = (str(item.get("document")), item.get("page"))
            if key in filing_keys:
                citations.append({
                    "kind": "filing",
                    "document": item.get("document"),
                    "page": item.get("page"),
                    "label": f"{item.get('document')} · p. {item.get('page')}",
                })
        elif kind == "equation" and item.get("mechanic") in equation_mechanics:
            mechanic = item["mechanic"]
            citations.append({
                "kind": "equation",
                "mechanic": mechanic,
                "label": f"{_eq.MECHANIC_LABELS.get(mechanic, mechanic)} — equation in force",
            })
        elif kind == "table" and item.get("table") in table_names:
            table = item["table"]
            citations.append({
                "kind": "table",
                "table": table,
                "label": f"{_eq.TABLE_LABELS.get(table, table)} in force",
            })
        elif kind == "ledger":
            years = [
                y for y in (item.get("years") or []) if y in ledger_years
            ]
            if years:
                citations.append({
                    "kind": "ledger",
                    "years": years,
                    "label": "Ledger · year " + ", ".join(str(y) for y in years),
                })
    return citations


def derive_citations(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Citations built from the context itself (deterministic path
    and the fallback when a model answer carries none)."""

    citations: List[Dict[str, Any]] = []
    for hit in (payload.get("filing_hits") or [])[:3]:
        citations.append({
            "kind": "filing",
            "document": hit.get("document"),
            "page": hit.get("page"),
            "label": f"{hit.get('document')} · p. {hit.get('page')}",
        })
    for mechanic, record in (payload.get("equations_in_force") or {}).items():
        if record:
            citations.append({
                "kind": "equation",
                "mechanic": mechanic,
                "label": f"{_eq.MECHANIC_LABELS.get(mechanic, mechanic)} — equation in force",
            })
    for table, view in (payload.get("tables_in_force") or {}).items():
        if view and view.get("inForce"):
            citations.append({
                "kind": "table",
                "table": table,
                "label": f"{_eq.TABLE_LABELS.get(table, table)} in force",
            })
    years = [row.get("year") for row in payload.get("ledger_rows") or []]
    years = [y for y in years if isinstance(y, int)]
    if years:
        citations.append({
            "kind": "ledger",
            "years": years,
            "label": f"Ledger · years {min(years)}–{max(years)}",
        })
    return citations


# ---------------------------------------------------------------------------
# Deterministic answers: absence, proposals, refusals, degraded mode
# ---------------------------------------------------------------------------


def _fmt_money(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"${value:,.2f}" if value % 1 else f"${value:,.0f}"
    return str(value)


def _absence_answer(
    ctx: ChatContext, route: Route, payload: Mapping[str, Any], message: str
) -> Optional[str]:
    """The first-class absence answer, or None when the context does
    hold material to answer from.  Three-state language throughout:
    covered by the documents / stated but not extracted / not in the
    documents."""

    slots = route.slots
    coverage = ctx.get_coverage_states()
    coverage_eq = coverage.get("equations") or {}

    if route.intent == INTENT_PRODUCT_OVERVIEW:
        if not ctx.has_filings:
            return (
                "This workspace has no filing documents, so there "
                "is nothing to tell the product's story from. Add "
                "the product's filing documents and run the analysis "
                "— I'll summarise it from them, with citations."
            )
        return None

    if route.intent == INTENT_FILING_FACT:
        # Coverage means a hit that speaks to the topic asked
        # about.  Hits matching only the question's generic framing
        # vocabulary ("what does the filing say about…") are not
        # coverage — they match nearly every page of a filing, and
        # treating them as coverage is how an absence question ends
        # up answered from unrelated passages, with citations.
        hits = payload.get("filing_hits") or []
        if any(hit.get("topical", True) for hit in hits):
            return None
        for mechanic in slots.get("mechanics") or []:
            entry = coverage_eq.get(mechanic) or {}
            if entry.get("state") == "stated":
                label = _eq.MECHANIC_LABELS.get(mechanic, mechanic)
                return (
                    f"The documents state the {label}, but it has not been "
                    "extracted into the model yet — that is an extraction "
                    "gap on our side, stated plainly. Re-running the "
                    "analysis or harvesting the equations is how it gets "
                    "extracted; I can't quote wording we haven't extracted."
                )
        return (
            "That is not in the documents: I searched the filing "
            "documents in this workspace and found no statement about "
            "it. If it belongs to this product, it would need to come "
            "from a document added to the workspace."
        )

    if route.intent == INTENT_MODEL_FACT:
        named_mechanics = slots.get("mechanics") or []
        named_tables = slots.get("tables") or []
        has_equation = any(
            (payload.get("equations_in_force") or {}).get(m)
            for m in named_mechanics
        )
        has_table = any(
            ((payload.get("tables_in_force") or {}).get(t) or {}).get("inForce")
            for t in named_tables
        )
        if has_equation or has_table or (not named_mechanics and not named_tables):
            return None
        for mechanic in named_mechanics:
            entry = coverage_eq.get(mechanic) or {}
            label = _eq.MECHANIC_LABELS.get(mechanic, mechanic)
            if entry.get("state") == "covered":
                where = ""
                if entry.get("filename"):
                    where = f" ({entry['filename']}"
                    if entry.get("page"):
                        where += f", p. {entry['page']}"
                    where += ")"
                return (
                    f"The documents cover the {label}{where}, but no "
                    "equation for it is in force yet — so it does not "
                    "calculate. Approving the extracted equation in "
                    "Inputs & Equations puts it in force."
                )
            if entry.get("state") == "stated":
                return (
                    f"The documents state the {label}, but it has not "
                    "been extracted into the model yet (stated but not "
                    "extracted) — there is no equation in force to quote."
                )
            return (
                f"The {label} is not in the documents: the filing set "
                "in this workspace does not state it, and no equation "
                "for it is in force."
            )
        for table in named_tables:
            candidates = (ctx.artifact.get("candidates") or {}).get(table) or []
            label = _eq.TABLE_LABELS.get(table, table)
            if candidates:
                return (
                    f"The {label} was extracted from the documents but "
                    "is not in force yet — accepting it in Inputs & "
                    "Equations puts its rows in force."
                )
            return (
                f"The {label} is not in the documents in force: no "
                "filed rows for it were extracted from this workspace's "
                "documents."
            )
    return None


def _scenario_proposal_answer(
    ctx: ChatContext, route: Route
) -> Dict[str, Any]:
    """A scenario change is named and proposed, never computed."""

    scenario = ctx.get_scenario() or {}
    request_keys = {
        "issue_age": "issue_age", "face_amount": "face_amount",
        "premium": "premium", "premium_mode": "premium_mode",
        "sex": "sex", "risk_class": "risk_class",
        "tobacco_status": "tobacco_status",
    }
    changes: List[Dict[str, Any]] = []
    for change in route.slots.get("scenario_changes") or []:
        field_name = change["field"]
        changes.append({
            "field": field_name,
            "label": change["label"],
            "currentValue": scenario.get(request_keys.get(field_name, field_name)),
            "newValue": change["newValue"],
        })
    named = "; ".join(
        f"{c['label']} → {_fmt_money(c['newValue']) if isinstance(c['newValue'], (int, float)) and c['field'] in ('premium', 'face_amount') else c['newValue']}"
        for c in changes
    )
    answer = (
        f"That's a scenario change: {named}. I don't compute "
        "projections — apply the change to the scenario form and run "
        "it through the projection engine, and the new ledger will be "
        "computed from the equations and tables in force."
    )
    return {
        "answer": answer,
        "scenario_proposal": {"changes": changes},
    }


_ARITHMETIC_ANSWER = (
    "I don't do arithmetic — every number I give you is quoted from "
    "the filing, the model in force, or the presented ledger, and a "
    "derived figure like that has to come from the projection engine "
    "so it stays auditable."
)


def _out_of_scope_answer() -> str:
    return (
        "That's outside what I can answer. I answer questions about "
        "this product — a summary of the product as a whole, what "
        "its filing documents say, the equations and tables in "
        "force, and the presented projection's ledger — "
        "always quoting the source, never computing new figures."
    )


def _no_run_answer(ctx: ChatContext) -> str:
    if ctx.has_filings:
        return (
            "There is no presented projection yet, so I can't explain "
            "ledger numbers that don't exist. Run a projection from "
            "the scenario form and I'll answer from its ledger; in the "
            "meantime I can answer questions about the filing "
            "documents and the model in force."
        )
    return (
        "There is no presented projection yet, and this workspace "
        "has no analyzed filing documents I can quote. Add documents "
        "and run the analysis, then run a projection — I'll answer "
        "from those sources."
    )


def _deterministic_summary(payload: Mapping[str, Any]) -> str:
    """A grounded answer assembled without a model (degraded mode):
    quotes the tool material directly."""

    parts: List[str] = []
    for hit in (payload.get("filing_hits") or [])[:2]:
        parts.append(
            f"From {hit.get('document')} (p. {hit.get('page')}): "
            f"“{hit.get('snippet')}”"
        )
    for mechanic, record in (payload.get("equations_in_force") or {}).items():
        if not record:
            continue
        label = record.get("label") or mechanic
        if record.get("statement"):
            parts.append(
                f"The {label} in force follows the filed statement: "
                f"“{record['statement']}”"
            )
        if record.get("timing"):
            parts.append(str(record["timing"]))
    for table, view in (payload.get("tables_in_force") or {}).items():
        if not view or not view.get("inForce"):
            continue
        rows = view.get("rows") or []
        shown = "; ".join(
            ", ".join(f"{k} {v}" for k, v in row.items()
                      if k != "provenance" and v is not None)
            for row in rows[:5]
        )
        parts.append(
            f"The {view.get('label')} in force holds "
            f"{view.get('rowCount')} matching row(s)"
            + (f": {shown}" if shown else "")
            + "."
        )
    rows = payload.get("ledger_rows") or []
    for row in rows[:12]:
        bits = []
        for key, label in (
            ("endingPolicyValue", "ending policy value"),
            ("cashValue", "cash value"),
            ("surrenderValue", "surrender value"),
            ("deathBenefit", "death benefit"),
            ("netAmountAtRisk", "net amount at risk"),
            ("coiCharge", "COI charge"),
        ):
            if row.get(key) is not None:
                bits.append(f"{label} {_fmt_money(row[key])}")
        if bits:
            parts.append(f"Year {row.get('year')}: " + "; ".join(bits) + ".")
    scenario = payload.get("scenario")
    if scenario and not rows:
        parts.append(f"The presented scenario is {json.dumps(scenario)}.")
    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# Stage 2: the answering call
# ---------------------------------------------------------------------------

_ANSWER_SYSTEM_PROMPT = (
    "You answer questions inside an actuarial workbench about ONE "
    "life insurance product and its presented illustration. You are "
    "given grounded context assembled from the product's filing "
    "documents, the equations and tables in force, and the presented "
    "projection's ledger. Rules, without exception:\n"
    "1. Answer ONLY from the provided context. Never use outside "
    "knowledge about this product.\n"
    "2. NEVER do arithmetic and never invent a figure. Every number "
    "in your answer must appear verbatim in the context (a ledger "
    "row, a table row, a scenario field). If the context does not "
    "contain a number, do not state one.\n"
    "3. Explain ledger behaviour by pointing at the rows and the "
    "definitions in force that produced them — attribute, don't "
    "recompute.\n"
    "4. If the context does not cover the question, say plainly that "
    "it is not in the documents / not in force, in those words.\n"
    "Output valid JSON only: {\"answer\": \"...\", \"citations\": "
    "[{\"kind\": \"filing\", \"document\": \"...\", \"page\": N} | "
    "{\"kind\": \"equation\", \"mechanic\": \"...\"} | {\"kind\": "
    "\"table\", \"table\": \"...\"} | {\"kind\": \"ledger\", "
    "\"years\": [N, ...]}]}. Cite every factual claim: filing facts "
    "cite document + page; model facts cite the equation or table in "
    "force; ledger facts cite the years."
)


def _answer_prompt(
    message: str,
    history: Optional[Sequence[Mapping[str, str]]],
    payload: Mapping[str, Any],
) -> str:
    turns = []
    for turn in (history or [])[-6:]:
        role = turn.get("role") or "user"
        content = str(turn.get("content") or "")[:600]
        if content:
            turns.append(f"{role}: {content}")
    history_block = "\n".join(turns) if turns else "(no prior turns)"
    task = ""
    if payload.get("intent") == INTENT_PRODUCT_OVERVIEW:
        task = (
            "Task: the user wants an overview of the product as a "
            "whole. Summarise what the product is from the filing "
            "passages, name the mechanics and tables in force, and "
            "say who the presented scenario covers — from the "
            "context only.\n\n"
        )
    return (
        f"Conversation so far:\n{history_block}\n\n"
        f"Question: {message}\n\n"
        f"{task}"
        f"Grounded context (JSON):\n{json.dumps(payload, default=str)}"
    )


#: An answer caller takes (system_prompt, user_prompt) and returns
#: the parsed JSON payload.  Injectable so tests stub the model.
AnswerCaller = Callable[[str, str], Any]
RouterCaller = Callable[[str, str], Any]


#: Completion budget for the answering (and routing) call.  It must be
#: stated explicitly: a local OpenAI-compatible server can cap a
#: completion far below what a long JSON answer needs when the request
#: stays silent (mlx-lm's server defaults to 512 tokens), which cut
#: overview answers off mid-JSON and dropped the chat to its
#: deterministic excerpt fallback.  4096 leaves generous headroom for
#: the longest grounded answer while staying a bounded request.
_ANSWER_MAX_TOKENS = 4096


def default_answer_caller() -> Optional[AnswerCaller]:
    """The production answer caller (OpenAI, existing plumbing).

    Returns None when no API key is configured — the pipeline then
    answers deterministically from the same grounded context."""

    try:
        from actuarypoc.extract.workspace_equations import (
            _chat_json,
            _openai_client_and_model,
        )

        client, model = _openai_client_and_model()
    except Exception:  # noqa: BLE001 - unconfigured model is a state, not a crash
        return None

    def call(system: str, user: str) -> Any:
        payload, _finish = _chat_json(
            client,
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=_ANSWER_MAX_TOKENS,
            repair_truncation=True,
        )
        return payload

    return call


def default_router_caller() -> Optional[RouterCaller]:
    """The production router caller — same plumbing, JSON mode."""

    return default_answer_caller()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def answer_question(
    ctx: ChatContext,
    message: str,
    history: Optional[Sequence[Mapping[str, str]]] = None,
    *,
    answer_caller: Optional[AnswerCaller] = None,
    router_caller: Optional[RouterCaller] = None,
) -> Dict[str, Any]:
    """One chat turn: route, ground, answer — under the doctrine.

    Returns {answer, intent, intentLabel, citations,
    scenarioProposal?}.  ``answer_caller=None`` means "use the
    production default"; pass ``False``-equivalent behaviour by
    giving a context whose intents resolve deterministically in
    tests (tests pass explicit stub callers instead).
    """

    message = (message or "").strip()
    route = classify_intent(message, router_caller)
    result: Dict[str, Any] = {
        "intent": route.intent,
        "intentLabel": INTENT_LABELS[route.intent],
        "citations": [],
    }
    if not message:
        result["answer"] = (
            "Ask me about this product — what the filing says, the "
            "equations and tables in force, or the presented "
            "projection's ledger."
        )
        return result

    # Deterministic screens first: these never reach the model.
    if route.intent == INTENT_OUT_OF_SCOPE:
        result["answer"] = _out_of_scope_answer()
        return result
    if route.intent == INTENT_SCENARIO_CHANGE:
        result.update(_scenario_proposal_answer(ctx, route))
        return result

    payload = assemble_context(ctx, route, message)

    if route.intent == INTENT_LEDGER and not ctx.has_run:
        result["answer"] = _no_run_answer(ctx)
        return result

    absence = _absence_answer(ctx, route, payload, message)
    if absence is not None:
        result["answer"] = absence
        # An absence answer carries NO citations: there is no
        # material to cite, and a citation assembled from generic
        # search hits would falsely imply the documents speak to
        # the topic they are silent on.
        result["citations"] = []
        return result

    if route.slots.get("arithmetic_request"):
        # The chat quotes the base figures; it never derives new
        # ones.  The grounded rows travel as citations.
        base = _deterministic_summary(payload)
        result["answer"] = (
            _ARITHMETIC_ANSWER + (f" The figures it would rest on: {base}" if base else "")
        )
        result["citations"] = derive_citations(payload)
        return result

    caller = answer_caller if answer_caller is not None else default_answer_caller()
    if caller is None:
        result["answer"] = _deterministic_summary(payload) or (
            "I have no grounded material to answer that from."
        )
        result["citations"] = derive_citations(payload)
        return result

    try:
        raw = caller(
            _ANSWER_SYSTEM_PROMPT,
            _answer_prompt(message, history, payload),
        )
    except Exception as exc:  # noqa: BLE001 - degrade, don't crash the bench
        result["answer"] = _deterministic_summary(payload) or (
            "The answering model could not be reached, and I have no "
            "grounded material to answer that from."
        )
        result["citations"] = derive_citations(payload)
        result["modelError"] = str(exc)[:200]
        return result

    answer = ""
    citations: List[Dict[str, Any]] = []
    if isinstance(raw, dict):
        answer = str(raw.get("answer") or "").strip()
        citations = validate_citations(raw.get("citations"), payload)
    if not answer:
        answer = _deterministic_summary(payload)
        citations = derive_citations(payload)
    else:
        cleaned, discarded = enforce_grounding(answer, payload, message)
        if discarded:
            result["groundingNote"] = (
                "Part of the model's answer was dropped: it stated "
                "figures the tools did not provide."
            )
            answer = cleaned or _deterministic_summary(payload)
        if not citations:
            citations = derive_citations(payload)
    result["answer"] = answer
    result["citations"] = citations
    return result
