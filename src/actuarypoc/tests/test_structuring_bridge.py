from __future__ import annotations

"""Phase 8 (the structuring bridge): harvest turns filing statements
into valid formula-language equations — or says precisely why not.

Diagnosis and design: docs/structuring-bridge.md.  The failure this
phase fixes, observed live on a real filing package (memo + form +
schedule of values, 78 slices): 13 stated calculations captured as
stated-but-UNMAPPED, zero structured.  The classes were locate
brittleness against the PDF text layer (words split mid-word),
model synthesis recorded as quotes, a template-less prompt the
model answered by declining or by writing a different JSON dialect,
single-mega-call model I/O that lost a whole pass to one decode
error, coverage blindness (crediting and NAR never captured), and
reasons recorded where the pane never showed them.

The fixture sentences below are the filing's own sentences (Promise
UL memo/form, quoted in the diagnosis) — including the split words
exactly as the PDF text layer produced them.
"""

import pytest

from actuarypoc.domain import equations as eq
from actuarypoc.extract import workspace_equations as weq

AT = "2026-10-26T15:00:00Z"

PREMIUM_TEXT = (
    "Premium Expense Charge A Premium Expense Charge is applied to each "
    "premium. The Premium Expense Charge is currently set at 10% for new "
    "issues."
)
ADMIN_TEXT = (
    "Administrative Charge An Administrative Charge is deducted at the "
    "beginning of each policy month until the Insured's Attained Age 121."
)
CREDITING_TEXT = (
    "The annual credited rate will not be less than the Guaranteed "
    "Minimum Annual Interest Rate shown in the Policy Specification "
    "which is currently set at 2% for new issues."
)
LOAN_TEXT = (
    "Interest will be credited to the loaned portion at a rate no less "
    "than the guaranteed annual loan credit interest rate listed on the "
    "Policy Specifications."
)
NAR_TEXT = (
    "Net Amount at Risk – is the difference between the Death Benefit "
    "and the Policy Va lue."
)
DB_TEXT = (
    "Option A: Death Benefit = Face amount. In no case will the death "
    "benefit be less than the amount required to qualify under "
    "Internal Revenue Code Section 7702."
)
APPENDIX_TEXT = "Maximum Cost of Insurance Rates are shown in Appendix 2."
SPLIT_DECREMENT_TEXT = (
    "The Surrender Charge decrease s by equal annual decrements until "
    "it reache s zero after the Surrender Charge Period."
)
CONVERSION_TEXT = (
    "Maximum monthly Cost of Insurance rates are converted from an "
    "annual to monthly COI rate by dividing by 12."
)


def _slice(text: str, page: int = 2, hint: str = "memo.pdf") -> dict:
    return {
        "document_hint": hint,
        "filename": hint,
        "page_start": page,
        "page_offsets": [],
        "text": text,
    }


def _no_model(slices):
    raise RuntimeError("no model in this test")


# ---------------------------------------------------------------------------
# Canonical location
# ---------------------------------------------------------------------------


def test_canon_locate_finds_split_word_quote():
    slices = [_slice(SPLIT_DECREMENT_TEXT)]
    located = weq._locate_statement(
        slices,
        "The Surrender Charge decreases by equal annual decrements "
        "until it reaches zero after the Surrender Charge Period.",
    )
    assert located is not None
    # The recorded statement is the filing's own sentence — split
    # words and all — never the model's cleaned-up copy.
    assert "decrease s" in located["statement"]


def test_canon_locate_finds_unicode_math_quote():
    slices = [_slice("The guaranteed monthly COI rate is 𝑞𝑥(12) as filed.")]
    located = weq._locate_statement(
        slices, "The guaranteed monthly COI rate is qx(12) as filed."
    )
    assert located is not None


def test_canon_locate_still_refuses_a_paraphrase():
    slices = [_slice(NAR_TEXT)]
    located = weq._locate_statement(
        slices,
        "The Minimum Death Benefit is equal to the Minimum Death "
        "Benefit Percentage multiplied by the Policy Value.",
    )
    assert located is None


# ---------------------------------------------------------------------------
# Model I/O: parsing and batching
# ---------------------------------------------------------------------------


def test_parse_model_payload_variants():
    assert weq._parse_model_payload('{"readings": []}') == {"readings": []}
    assert weq._parse_model_payload('```json\n{"readings": []}\n```') == {
        "readings": []
    }
    wrapped = 'Here are the readings: {"readings": [1]} — done.'
    assert weq._parse_model_payload(wrapped) == {"readings": [1]}
    with pytest.raises(ValueError):
        weq._parse_model_payload("no json here at all")


def test_reading_batches_group_by_document_under_budget():
    # The budget is measured on what the prompt actually carries —
    # each slice truncated to 6000 chars — so seven full-size slices
    # of one document split 6 + 1 under the 40000-char budget, and a
    # second document always starts its own batch.
    slices = [_slice("x" * 7000, hint="a.pdf") for _ in range(7)]
    slices.append(_slice("z" * 100, hint="b.pdf"))
    batches = weq._reading_batches(slices)
    assert [len(batch) for batch in batches] == [6, 1, 1]
    small = [_slice("a", hint="a.pdf"), _slice("b", hint="a.pdf")]
    assert len(weq._reading_batches(small)) == 1


# ---------------------------------------------------------------------------
# Deterministic assists on the filing's own sentences
# ---------------------------------------------------------------------------


def test_deterministic_assists_structure_the_real_idioms():
    slices = [
        _slice(PREMIUM_TEXT), _slice(ADMIN_TEXT), _slice(CREDITING_TEXT),
        _slice(NAR_TEXT, page=4), _slice(DB_TEXT, page=1),
    ]
    candidates = weq.deterministic_harvest(slices)
    by_mechanic = {}
    for candidate in candidates:
        if candidate.get("body") is not None:
            by_mechanic.setdefault(candidate["mechanic"], candidate)
    assert set(by_mechanic) == {
        "premium_load", "policy_fees", "crediting",
        "nar_definition", "death_benefit",
    }
    for mechanic, candidate in by_mechanic.items():
        assert eq.validate_equation(mechanic, candidate["body"]) == []
    # The stated percentage is in the words, so the body carries it
    # as a const — not a fee-table lookup that would default to 0.
    assert by_mechanic["premium_load"]["body"] == {
        "mul": [{"qty": "premium_due"}, {"const": 0.1}]
    }
    assert by_mechanic["policy_fees"]["body"] == eq.policy_fees_body()
    assert by_mechanic["crediting"]["body"] == eq.crediting_body()
    assert by_mechanic["nar_definition"]["body"] == eq.nar_body("unadjusted")
    assert by_mechanic["death_benefit"]["body"] == eq.death_benefit_body()


def test_crediting_pattern_does_not_fire_on_the_loan_rate():
    candidates = weq.deterministic_harvest([_slice(LOAN_TEXT)])
    assert not [c for c in candidates if c["mechanic"] == "crediting"]


# ---------------------------------------------------------------------------
# Table pointers: a lookup is proposed only against a table held
# ---------------------------------------------------------------------------


def test_table_pointer_without_the_table_records_the_reason():
    candidates = weq._table_pointer_candidates({}, [_slice(APPENDIX_TEXT)])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["mechanic"] == "coi_charge"
    assert candidate["body"] is None
    assert "no usable COI table" in candidate["note"]


def test_table_pointer_with_the_table_structures_the_lookup():
    artifact = {"usable": {"coi": [{"rate_unit": "per_1000_monthly"}]}}
    candidates = weq._table_pointer_candidates(artifact, [_slice(APPENDIX_TEXT)])
    assert candidates[0]["body"] == eq.coi_body_for_unit("per_1000_monthly")


def test_conversion_statement_is_captured_not_structured():
    candidates = weq._table_pointer_candidates({}, [_slice(CONVERSION_TEXT)])
    assert len(candidates) == 1
    assert candidates[0]["body"] is None
    assert "produces the rate table" in candidates[0]["note"]


# ---------------------------------------------------------------------------
# The repair loop
# ---------------------------------------------------------------------------

_DIALECT_BODY = {
    "operator": "mul",
    "operands": [{"qty": "premium_due"}, {"const": 0.1}],
}
_FIXED_BODY = {"mul": [{"qty": "premium_due"}, {"const": 0.1}]}


def _dialect_caller(readings_body):
    def caller(slices):
        return {
            "readings": [{
                "mechanic": "premium_load",
                "statement": (
                    "The Premium Expense Charge is currently set at "
                    "10% for new issues."
                ),
                "page": 2,
                "timing": None,
                "body": readings_body,
            }],
            "model": "fake",
        }
    return caller


def test_repair_loop_fixes_the_wrong_dialect():
    outcome = weq.harvest_equations(
        {}, [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_dialect_caller(_DIALECT_BODY),
        repair_caller=lambda m, s, b, e: _FIXED_BODY,
    )
    records = weq.records_for(outcome["artifact"], "premium_load")
    pendings = [r for r in records if r["state"] == "pending"]
    assert pendings and pendings[0]["body"] == _FIXED_BODY
    assert outcome["repairLog"]
    assert outcome["repairLog"][0]["outcome"] == "fixed"


def test_repair_declined_keeps_the_validation_evidence():
    outcome = weq.harvest_equations(
        {}, [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_dialect_caller(_DIALECT_BODY),
        repair_caller=lambda m, s, b, e: None,
    )
    records = weq.records_for(outcome["artifact"], "premium_load")
    unmapped = [r for r in records if r["state"] == "unmapped"]
    assert unmapped
    source = unmapped[0]["source"]
    assert source.get("validationErrors")
    assert source.get("rejectedBody") == _DIALECT_BODY


def test_injected_fake_caller_never_triggers_repair():
    def forbidden_repair(*args):
        raise AssertionError("repair must not run for injected fakes")

    outcome = weq.harvest_equations(
        {}, [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_dialect_caller(_DIALECT_BODY),
        # repair_caller deliberately not injected: with a fake model
        # caller the default repair must stay off too.
    )
    assert outcome["repairLog"] == []
    records = weq.records_for(outcome["artifact"], "premium_load")
    assert any(r["state"] == "unmapped" for r in records)
    with pytest.raises(AssertionError):
        forbidden_repair()


# ---------------------------------------------------------------------------
# Repair guardrails (added after the first live rehearsal)
# ---------------------------------------------------------------------------


def test_repair_that_changes_the_arithmetic_is_rejected():
    invented = {"max": [{"const": 40}, {"qty": "account_value"}]}

    outcome = weq.harvest_equations(
        {}, [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_dialect_caller(_DIALECT_BODY),
        repair_caller=lambda m, s, b, e: invented,
    )
    records = weq.records_for(outcome["artifact"], "premium_load")
    unmapped = [r for r in records if r["state"] == "unmapped"]
    assert unmapped
    # The record keeps the ORIGINAL proposed body as the evidence —
    # not the repair's invention.
    assert unmapped[0]["source"].get("rejectedBody") == _DIALECT_BODY
    assert outcome["repairLog"][0]["outcome"].startswith("rejected")


def test_repair_may_rename_an_invalid_quantity():
    wrong_name = {"mul": [{"qty": "premium"}, {"const": 0.1}]}
    assert eq.validate_equation("premium_load", wrong_name)
    outcome = weq.harvest_equations(
        {}, [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_dialect_caller(wrong_name),
        repair_caller=lambda m, s, b, e: _FIXED_BODY,
    )
    records = weq.records_for(outcome["artifact"], "premium_load")
    assert any(r["state"] == "pending" for r in records)
    assert outcome["repairLog"][0]["outcome"] == "fixed"


def test_misfiling_is_recorded_not_structured():
    ncsv_text = (
        "The Net Cash Surrender Value at the time of full surrender "
        "will be the Policy Value less any Surrender Charge."
    )

    def misfiling_caller(slices):
        return {
            "readings": [{
                "mechanic": "nar_definition",
                "statement": ncsv_text,
                "page": 3,
                "timing": None,
                "body": eq.nar_body("unadjusted"),
            }],
            "model": "fake",
        }

    outcome = weq.harvest_equations(
        {}, [_slice(ncsv_text, page=3)], at=AT,
        model_caller=misfiling_caller,
    )
    records = weq.records_for(outcome["artifact"], "nar_definition")
    assert records
    assert all(r["state"] == "unmapped" for r in records)
    assert "misfil" in (records[0]["source"].get("note") or "")


def test_bare_lookup_body_blocked_until_the_table_exists():
    charge_text = (
        "The Cost of Insurance Charge is equal to the Maximum Monthly "
        "Cost of Insurance Rate multiplied by the Net Amount at Risk "
        "divided by 1,000."
    )

    def charge_caller(slices):
        return {
            "readings": [{
                "mechanic": "coi_charge",
                "statement": charge_text,
                "page": 10,
                "timing": None,
                "body": eq.coi_body_for_unit("per_1000_monthly"),
            }],
            "model": "fake",
        }

    outcome = weq.harvest_equations(
        {}, [_slice(charge_text, page=10)], at=AT, model_caller=charge_caller,
    )
    records = weq.records_for(outcome["artifact"], "coi_charge")
    blocked = [r for r in records if r["state"] == "unmapped"]
    assert blocked
    assert blocked[0]["source"].get("blockedReason") == "table_not_extracted"
    assert blocked[0]["source"].get("rejectedBody") == \
        eq.coi_body_for_unit("per_1000_monthly")

    with_table = weq.harvest_equations(
        {"usable": {"coi": [{"rate_unit": "per_1000_monthly"}]}},
        [_slice(charge_text, page=10)], at=AT, model_caller=charge_caller,
    )
    records = weq.records_for(with_table["artifact"], "coi_charge")
    assert any(r["state"] == "pending" for r in records)


def test_statementless_readings_record_nothing():
    def empty_caller(slices):
        return {
            "readings": [{"mechanic": "policy_fees", "body": None}],
            "model": "fake",
        }

    outcome = weq.harvest_equations(
        {}, [_slice(ADMIN_TEXT)], at=AT, model_caller=empty_caller,
    )
    assert any("no statement" in w for w in outcome["warnings"])
    fees = weq.records_for(outcome["artifact"], "policy_fees")
    # Only the deterministic admin-charge record exists.
    assert len(fees) == 1 and fees[0]["state"] == "pending"


def test_model_reading_cannot_supersede_a_table_pointer_record():
    def pointer_caller(slices):
        return {
            "readings": [{
                "mechanic": "coi_charge",
                "statement": APPENDIX_TEXT,
                "page": 2,
                "timing": None,
                "body": eq.coi_body_for_unit("per_1000_monthly"),
            }],
            "model": "fake",
        }

    outcome = weq.harvest_equations(
        {}, [_slice(APPENDIX_TEXT)], at=AT, model_caller=pointer_caller,
    )
    records = weq.records_for(outcome["artifact"], "coi_charge")
    pointer = [r for r in records if r["source"].get("assist") == "table_pointer"]
    assert pointer and pointer[0]["state"] == "unmapped"
    assert not any(r["state"] == "pending" for r in records)


# ---------------------------------------------------------------------------
# Upgrade and supersede
# ---------------------------------------------------------------------------


def test_upgrade_supersedes_the_unmapped_record_for_the_statement():
    first = weq.harvest_equations(
        {}, [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_dialect_caller(_DIALECT_BODY),
    )
    before = weq.records_for(first["artifact"], "premium_load")
    assert any(r["state"] == "unmapped" for r in before)
    second = weq.harvest_equations(
        first["artifact"], [_slice(PREMIUM_TEXT)], at=AT,
        model_caller=_no_model,
    )
    records = weq.records_for(second["artifact"], "premium_load")
    states = sorted(r["state"] for r in records)
    assert "pending" in states
    assert "superseded" in states


def test_located_statement_supersedes_a_legacy_unlocated_claim():
    claim = (
        "The Surrender Charge decreases by equal annual decrements "
        "until it reaches zero after the Surrender Charge Period."
    )
    legacy = weq.new_record(
        mechanic="surrender_charge",
        body=None,
        state="unmapped",
        source={
            "kind": "document",
            "statement": None,
            "statementKey": None,
            "note": (
                "The model proposed a reading of a statement it "
                f"quoted as “{claim}”, which could not be located "
                "in the document text, so nothing was recorded as "
                "the filing's words."
            ),
        },
        at=AT,
    )
    artifact = {"equations": [legacy]}
    outcome = weq.harvest_equations(
        artifact, [_slice(SPLIT_DECREMENT_TEXT)], at=AT,
        model_caller=_no_model,
    )
    records = weq.records_for(outcome["artifact"], "surrender_charge")
    by_id = {r["id"]: r for r in records}
    assert by_id[legacy["id"]]["state"] == "superseded"
    assert any(
        r["state"] == "unmapped" and r["id"] != legacy["id"]
        for r in records
    )


# ---------------------------------------------------------------------------
# Coverage accounting
# ---------------------------------------------------------------------------


def test_coverage_names_mechanics_with_no_statement_found():
    outcome = weq.harvest_equations(
        {}, [_slice(NAR_TEXT, page=4)], at=AT,
        model_caller=lambda slices: {"readings": [], "model": "fake"},
    )
    covered = {entry["mechanic"] for entry in outcome["coverage"]}
    assert "nar_definition" not in covered
    assert covered == set(eq.MECHANICS) - {"nar_definition"}
    assert all(
        entry["status"] == "no_statement_found"
        for entry in outcome["coverage"]
    )
