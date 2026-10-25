"""Phase 4 (the rule bank): market variations as banked switches.

Eddy (Aug 7, 2026) described how commercial modeling software works:
every market variation is a pre-built switch — COI taken at the
beginning, middle, or end of the period; a surrender charge on this
basis or that — and a "product" is a combination of switches plus
rates.  Phase 3 gave the chassis corrections whose variants were the
seed of that bank.  This module is the bank itself:

* a **registry** (:data:`SWITCHES`) of every variation the projection
  engine may execute, each with a stable id, the mechanic it belongs
  to, a plain-language actuarial description, a parameter schema, and
  the deterministic implementation the engine dispatches to;
* the **implementations** themselves — small pure functions whose
  arithmetic is the arithmetic the projection loop historically
  carried inline, moved here verbatim so the loop can dispatch instead
  of improvising;
* **schedule materialisers** that turn a switch's parameters (a graded
  schedule, a banded/piecewise schedule) into validated table rows;
* **parameter validation** driven by the schemas, shared by the
  correction layer and the proposal layer.

Engine purity rule: for every mechanic the bank covers, the projection
loop executes banked implementations only.  Fallbacks are not hidden
in the loop — they are registered here as switches of kind
``"placeholder"``, labelled as placeholders in every derivation, and
used only when no evidenced input is in force.  A value the bank does
not know (an unbanked rate unit, an unbanked timing) is an error, not
an improvisation.

Governance: a variation enters the bank only as code + tests in this
repository (see ``docs/rule-bank.md``).  Nothing about a switch is
learned at run time, and no model output ever becomes a switch without
an actuary confirming the mapping first (the proposal layer).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Registry types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamSpec:
    """One parameter of a banked switch, for validation and display."""

    name: str
    kind: str  # "number" | "integer" | "choice" | "bands"
    label: str
    required: bool = True
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[str, ...] = ()

    def view(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "required": self.required,
        }
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        if self.choices:
            out["choices"] = list(self.choices)
        return out


@dataclass(frozen=True)
class BankedSwitch:
    """One banked variation: a registry entry plus its implementation.

    ``kind`` says how the engine (or the correction/proposal layers)
    consumes the switch:

    * ``rate_unit`` — a COI charge computed from a table rate;
    * ``timing_step`` — the in-month sequencing of the COI deduction;
    * ``nar_definition`` — how the COI net amount at risk is measured;
    * ``surrender_basis`` — a surrender charge from a schedule row;
    * ``fee_unit`` — a fee row's monthly amount / premium load;
    * ``crediting`` — how interest is credited;
    * ``schedule_materializer`` — parameters -> validated table rows;
    * ``placeholder`` — a labelled fallback used only when no evidenced
      input is in force; never presented as a filed calculation.
    """

    id: str
    mechanic: str
    label: str
    description: str
    kind: str
    params: Tuple[ParamSpec, ...]
    implementation: Callable[..., Any]

    def view(self) -> Dict[str, Any]:
        """JSON-safe registry view (no implementation) for API/UI use."""

        return {
            "id": self.id,
            "mechanic": self.mechanic,
            "label": self.label,
            "description": self.description,
            "kind": self.kind,
            "params": [param.view() for param in self.params],
        }


# ---------------------------------------------------------------------------
# COI charge from a table rate (rate_unit switches)
#
# The arithmetic is the projection loop's, verbatim: a monthly charge
# measured on the COI net amount at risk for the month.
# ---------------------------------------------------------------------------


def _coi_per_1000_monthly(rate: float, nar: float) -> float:
    return nar / 1000.0 * rate


def _coi_per_1000_annual(rate: float, nar: float) -> float:
    return nar / 1000.0 * rate / 12.0


def _coi_percent_nar_annual(rate: float, nar: float) -> float:
    return nar * rate / 12.0


# ---------------------------------------------------------------------------
# Net amount at risk definitions (nar_definition switches)
#
# Both take the filed NAR factor as an argument; the factor-adjusted
# definition applies it, the unadjusted one does not.  (The loop
# historically expressed "unadjusted" as an effective factor of 1.0;
# the two formulations are arithmetically identical.)
# ---------------------------------------------------------------------------


def _nar_factor_adjusted(death_benefit: float, value: float, factor: float) -> float:
    return max(death_benefit / factor - value, 0.0)


def _nar_unadjusted(death_benefit: float, value: float, factor: float) -> float:
    return max(death_benefit - value, 0.0)


# ---------------------------------------------------------------------------
# COI deduction timing (timing_step switches)
#
# Each step receives the month's opening account value (after premium
# and premium load), the month's fee total, the monthly interest rate,
# and the loop's own month-COI measurer + NAR tracker, and returns
# ``(value, interest_credited, coi_charged)`` for the month.  Fees keep
# their position in every variant — only the COI deduction moves.  The
# three sequences are the projection loop's branches, verbatim.
# ---------------------------------------------------------------------------


def _coi_step_beginning(value, monthly_fee, interest_rate, month_coi, track_nar):
    """COI measured on the post-premium value and deducted, together
    with the month's fees, before interest is credited (the historical
    default sequence)."""

    month_coi_charge, charge_nar = month_coi(value)
    track_nar(charge_nar)
    value = max(value - month_coi_charge - monthly_fee, 0.0)
    month_interest = value * interest_rate
    value += month_interest
    return value, month_interest, month_coi_charge


def _coi_step_middle(value, monthly_fee, interest_rate, month_coi, track_nar):
    """Half the COI before interest (NAR measured on the pre-interest
    value), half after (NAR re-measured on the post-interest value)."""

    first_coi, first_nar = month_coi(value)
    track_nar(first_nar)
    first_half = first_coi / 2.0
    value = max(value - first_half - monthly_fee, 0.0)
    month_interest = value * interest_rate
    value += month_interest
    second_coi, second_nar = month_coi(value)
    track_nar(second_nar)
    second_half = second_coi / 2.0
    value = max(value - second_half, 0.0)
    return value, month_interest, first_half + second_half


def _coi_step_end(value, monthly_fee, interest_rate, month_coi, track_nar):
    """Fees deducted and interest credited first; the COI charge is
    measured on the post-interest value and deducted last."""

    value = max(value - monthly_fee, 0.0)
    month_interest = value * interest_rate
    value += month_interest
    month_coi_charge, charge_nar = month_coi(value)
    track_nar(charge_nar)
    value = max(value - month_coi_charge, 0.0)
    return value, month_interest, month_coi_charge


# ---------------------------------------------------------------------------
# Surrender charge bases (surrender_basis switches)
#
# A loaded schedule is applied exactly on the basis it states.  Each
# implementation takes the row's charge value plus the two candidate
# bases and returns the year's surrender charge.
# ---------------------------------------------------------------------------


def _surrender_percent_account_value(charge: float, policy_value: float, face_amount: float) -> float:
    return policy_value * charge


def _surrender_percent_face(charge: float, policy_value: float, face_amount: float) -> float:
    return face_amount * charge


def _surrender_per_1000_face(charge: float, policy_value: float, face_amount: float) -> float:
    return face_amount / 1000.0 * charge


def _surrender_fixed(charge: float, policy_value: float, face_amount: float) -> float:
    return charge


# ---------------------------------------------------------------------------
# Fee units (fee_unit switches)
#
# ``monthly_fee`` implementations give one row's monthly deduction;
# the premium-load row is applied against each premium payment instead
# (its monthly deduction is zero — the load is taken from premiums,
# never double-counted as a monthly fee).
# ---------------------------------------------------------------------------


def _fee_monthly_fixed(amount: float, *, face_amount: float, payment_due: bool) -> float:
    return amount


def _fee_modal_fixed(amount: float, *, face_amount: float, payment_due: bool) -> float:
    return amount if payment_due else 0.0


def _fee_per_1000_face_annual(amount: float, *, face_amount: float, payment_due: bool) -> float:
    return face_amount / 1000.0 * amount / 12.0


def _fee_annual_fixed(amount: float, *, face_amount: float, payment_due: bool) -> float:
    return amount / 12.0


def _fee_percent_premium_monthly(amount: float, *, face_amount: float, payment_due: bool) -> float:
    return 0.0


def premium_load_for_row(amount: float, gross_premium: float) -> float:
    """Premium expense load taken from one premium payment."""

    return gross_premium * amount


# ---------------------------------------------------------------------------
# Crediting (crediting switches)
# ---------------------------------------------------------------------------


def _monthly_rate_from_annual(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


# ---------------------------------------------------------------------------
# Placeholders (placeholder switches)
#
# Labelled fallbacks, used only when no evidenced input is in force.
# They are registered so the engine's use of them is explicit and every
# derivation can name them — never silent improvisations.
# ---------------------------------------------------------------------------


def coi_placeholder_monthly_charge(face_amount: float, flat_annual_rate: float) -> float:
    """Placeholder COI: a flat annual rate on the face amount, / 12.

    Deliberately NOT rate x net amount at risk — that is what makes it
    a placeholder, and the ledger says so on every line it produces.
    """

    return face_amount * flat_annual_rate / 12.0


def surrender_placeholder_charge(
    year: int, policy_value: float, *, period_years: int, max_pct: float
) -> Tuple[float, Optional[float]]:
    """Placeholder surrender charge: a percentage of the ending account
    value declining linearly to zero over the surrender period.

    Returns ``(charge, percent)``; ``percent`` is None once the period
    has expired (no charge applies).
    """

    if year > period_years:
        return 0.0, None
    remaining = period_years - year + 1
    pct = max_pct * (remaining / period_years)
    return policy_value * pct, pct


def fee_fallback_monthly(configured_annual_fee: float) -> float:
    """Fallback fee when no fee schedule is in force: the configured
    annual policy/admin fee spread evenly over the months."""

    return configured_annual_fee / 12.0


# ---------------------------------------------------------------------------
# Schedule materialisers (schedule_materializer switches)
#
# Parameters -> canonical table rows (unvalidated, unstamped).  The
# caller validates the rows with the ingestion validators and stamps
# provenance, exactly as the Phase 3 corrections did — the bank owns
# the *shape* of the schedule, the workspace layers own its provenance.
# ---------------------------------------------------------------------------


MAX_SCHEDULE_DURATION = 121  # workspace_ul_mechanics.MAX_DURATION


def materialize_graded_surrender(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A surrender schedule that grades linearly to zero.

    Starts at the corrected value in year 1 and declines by equal steps
    to zero at the end of the grading period — the shape Eddy described
    ("8% of account value, grading to 0 over 10 years").
    """

    basis = params["basis"]
    grading_years = int(params["gradingYears"])
    unit = {
        "percent_account_value": "percent_account_value",
        "percent_face": "percent_face",
        "flat_amount": "fixed",
    }[basis]
    start = float(params["percent"]) if basis != "flat_amount" else float(params["amount"])
    rows: List[Dict[str, Any]] = []
    for duration in range(1, grading_years + 1):
        factor = (grading_years - duration + 1) / grading_years
        rows.append({
            "duration": duration,
            "issue_age": None,
            "sex": None,
            "charge": start * factor,
            "charge_unit": unit,
        })
    return rows


def _band_value(band: Dict[str, Any], year: int) -> Tuple[float, str]:
    """The (value, unit) a band assigns to one duration.

    A band states a start value and, optionally, an end value it grades
    linearly toward across the band ("gradeTo"); without ``gradeTo``
    the value is constant within the band.
    """

    start = float(band["value"])
    end = band.get("gradeTo")
    if end is None:
        return start, str(band["unit"])
    first, last = int(band["fromYear"]), int(band["toYear"])
    if last <= first:
        return float(end), str(band["unit"])
    fraction = (year - first) / (last - first)
    return start + (float(end) - start) * fraction, str(band["unit"])


def materialize_banded_rows(mechanic: str, bands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expand duration bands into one canonical row per duration.

    Bands must be contiguous from year 1 (validated by
    :func:`validate_bands` before this is called).  Each returned row
    carries a ``_band`` entry describing the band it came from; the
    caller moves it into the row's provenance when stamping, so the
    ledger can name the band applied in each period.
    """

    rows: List[Dict[str, Any]] = []
    for index, band in enumerate(bands):
        first, last = int(band["fromYear"]), int(band["toYear"])
        label = f"years {first}+" if band.get("openEnded") else f"years {first}–{last}"
        band_info = {
            "index": index + 1,
            "label": label,
            "fromYear": first,
            "toYear": last,
            "unit": str(band["unit"]),
        }
        for year in range(first, last + 1):
            value, unit = _band_value(band, year)
            if mechanic == "surrender":
                row = {
                    "duration": year,
                    "issue_age": None,
                    "sex": None,
                    "charge": value,
                    "charge_unit": unit,
                }
            elif mechanic == "coi":
                row = {
                    "duration": year,
                    "attained_age": None,
                    "sex": None,
                    "risk_class": None,
                    "tobacco_status": None,
                    "rate": value,
                    "rate_unit": unit,
                }
            else:
                raise ValueError(f"Banded schedules are not banked for {mechanic!r}")
            row["_band"] = dict(band_info)
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Parameter validation (driven by the registry schemas)
# ---------------------------------------------------------------------------


def validate_params(switch: "BankedSwitch", params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalise parameters against a switch's schema.

    Raises ValueError with an actuary-readable message on any defect.
    Returns the normalised parameter dict (only schema parameters,
    coerced to their kinds).  ``bands`` parameters are validated by
    :func:`validate_bands` against the switch's mechanic.
    """

    params = params or {}
    normalised: Dict[str, Any] = {}
    for spec in switch.params:
        raw = params.get(spec.name)
        if raw is None:
            if spec.required:
                raise ValueError(f"{switch.label}: {spec.label} is required")
            continue
        if spec.kind == "choice":
            value = str(raw)
            if value not in spec.choices:
                raise ValueError(
                    f"{switch.label}: {spec.label} must be one of: "
                    + ", ".join(spec.choices)
                )
            normalised[spec.name] = value
        elif spec.kind == "integer":
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{switch.label}: {spec.label} must be a whole number") from exc
            if isinstance(raw, float) and not float(raw).is_integer():
                raise ValueError(f"{switch.label}: {spec.label} must be a whole number")
            _check_range(switch, spec, float(value))
            normalised[spec.name] = value
        elif spec.kind == "number":
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{switch.label}: {spec.label} must be a number") from exc
            if not math.isfinite(value):
                raise ValueError(f"{switch.label}: {spec.label} must be a finite number")
            _check_range(switch, spec, value)
            normalised[spec.name] = value
        elif spec.kind == "bands":
            normalised[spec.name] = validate_bands(switch.mechanic, list(raw))
        else:  # pragma: no cover - registry authoring error
            raise ValueError(f"Unknown parameter kind {spec.kind!r} on {switch.id}")
    if switch.id == "surrender.schedule.graded":
        # Cross-field rule: exactly one starting value, chosen by basis.
        if normalised.get("basis") in ("percent_account_value", "percent_face"):
            if normalised.get("percent") is None:
                raise ValueError(
                    "Graded surrender schedule: A percentage is required for a "
                    "percentage surrender basis"
                )
            if normalised["percent"] <= 0:
                raise ValueError(
                    "Graded surrender schedule: The surrender percentage must be "
                    "greater than 0 and at most 100%"
                )
        elif normalised.get("basis") == "flat_amount":
            if normalised.get("amount") is None:
                raise ValueError(
                    "Graded surrender schedule: A dollar amount is required for a "
                    "flat surrender basis"
                )
            if normalised["amount"] <= 0:
                raise ValueError(
                    "Graded surrender schedule: The flat surrender amount must be "
                    "greater than 0"
                )
    return normalised


def _check_range(switch: "BankedSwitch", spec: ParamSpec, value: float) -> None:
    if spec.minimum is not None and value < spec.minimum:
        raise ValueError(f"{switch.label}: {spec.label} must be at least {spec.minimum:g}")
    if spec.maximum is not None and value > spec.maximum:
        raise ValueError(f"{switch.label}: {spec.label} must be at most {spec.maximum:g}")


#: The units a band may state, per mechanic (the row units the bank's
#: basis switches execute).
BAND_UNITS: Dict[str, Tuple[str, ...]] = {
    "surrender": ("percent_account_value", "percent_face", "per_1000_face", "fixed"),
    "coi": ("per_1000_monthly", "per_1000_annual", "percent_nar_annual"),
}


def validate_bands(mechanic: str, bands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate + normalise a banded schedule's band list.

    Bands must start at year 1, be contiguous (no gaps, no overlaps),
    and ascend.  Only the final band may be open-ended (``toYear``
    null); it is normalised to :data:`MAX_SCHEDULE_DURATION` with
    ``openEnded`` set.  Band values must be non-negative; percentage
    units must be at most 100%.
    """

    if mechanic not in BAND_UNITS:
        raise ValueError(f"Banded schedules are not banked for {mechanic!r}")
    if not bands:
        raise ValueError("A banded schedule needs at least one band")
    normalised: List[Dict[str, Any]] = []
    expected_from = 1
    for index, raw in enumerate(bands):
        if not isinstance(raw, dict):
            raise ValueError(f"Band {index + 1}: expected an object describing the band")
        try:
            first = int(raw.get("fromYear"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Band {index + 1}: fromYear must be a whole number of years") from exc
        if first != expected_from:
            raise ValueError(
                f"Band {index + 1}: bands must be contiguous from year 1 with no gaps "
                f"or overlaps (expected this band to start at year {expected_from}, got {first})"
            )
        is_last = index == len(bands) - 1
        raw_to = raw.get("toYear")
        open_ended = raw_to is None
        if open_ended and not is_last:
            raise ValueError(f"Band {index + 1}: only the final band may be open-ended")
        try:
            last = MAX_SCHEDULE_DURATION if open_ended else int(raw_to)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Band {index + 1}: toYear must be a whole number of years") from exc
        if last < first or last > MAX_SCHEDULE_DURATION:
            raise ValueError(
                f"Band {index + 1}: toYear must be between {first} and {MAX_SCHEDULE_DURATION}"
            )
        unit = str(raw.get("unit") or "")
        if unit not in BAND_UNITS[mechanic]:
            raise ValueError(
                f"Band {index + 1}: unit must be one of: " + ", ".join(BAND_UNITS[mechanic])
            )
        band: Dict[str, Any] = {
            "fromYear": first,
            "toYear": last,
            "unit": unit,
            "value": _band_number(raw.get("value"), index, "value"),
        }
        if open_ended:
            band["openEnded"] = True
        if raw.get("gradeTo") is not None:
            band["gradeTo"] = _band_number(raw.get("gradeTo"), index, "gradeTo")
        _check_band_value_range(band, index)
        normalised.append(band)
        expected_from = last + 1
    return normalised


def _band_number(raw: Any, index: int, field: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Band {index + 1}: {field} must be a number") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Band {index + 1}: {field} must be zero or greater")
    return value


def _check_band_value_range(band: Dict[str, Any], index: int) -> None:
    unit = band["unit"]
    for field in ("value", "gradeTo"):
        value = band.get(field)
        if value is None:
            continue
        if unit in ("percent_account_value", "percent_face", "percent_nar_annual") and value > 1:
            raise ValueError(f"Band {index + 1}: a percentage {field} must be at most 100%")
        if unit.startswith("per_1000") and value > 1000:
            raise ValueError(f"Band {index + 1}: a per-$1,000 {field} must be at most 1000")


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def _switch(switch_id, mechanic, label, description, kind, params, implementation):
    return BankedSwitch(
        id=switch_id, mechanic=mechanic, label=label, description=description,
        kind=kind, params=tuple(params), implementation=implementation,
    )


_RATE_PARAM = ParamSpec("rate", "number", "Rate", minimum=0)
_CHARGE_PARAM = ParamSpec("charge", "number", "Charge", minimum=0)
_AMOUNT_PARAM = ParamSpec("amount", "number", "Amount", minimum=0)

SWITCHES: Dict[str, BankedSwitch] = {
    switch.id: switch
    for switch in [
        # --- COI: charge from a table rate -------------------------------
        _switch(
            "coi.rate.per_1000_monthly", "coi", "COI rate per $1,000 (monthly)",
            "Each month: COI charge = (COI net amount at risk / 1,000) x the "
            "monthly rate per $1,000 stated in the schedule.",
            "rate_unit", [_RATE_PARAM], _coi_per_1000_monthly,
        ),
        _switch(
            "coi.rate.per_1000_annual", "coi", "COI rate per $1,000 (annual)",
            "Each month: COI charge = (COI net amount at risk / 1,000) x "
            "(the annual rate per $1,000 / 12).",
            "rate_unit", [_RATE_PARAM], _coi_per_1000_annual,
        ),
        _switch(
            "coi.rate.percent_nar_annual", "coi", "COI rate as a percentage of NAR (annual)",
            "Each month: COI charge = COI net amount at risk x (the annual "
            "percentage rate / 12).",
            "rate_unit", [_RATE_PARAM], _coi_percent_nar_annual,
        ),
        # --- COI: deduction timing ---------------------------------------
        _switch(
            "coi.timing.beginning", "coi", "COI deducted at the beginning of the month",
            "The COI charge is measured on the post-premium account value and "
            "deducted, together with the month's fees, before interest is credited.",
            "timing_step", [], _coi_step_beginning,
        ),
        _switch(
            "coi.timing.middle", "coi", "COI deducted in the middle of the month",
            "Half the COI charge is deducted before interest is credited (net "
            "amount at risk measured on the pre-interest value) and half after "
            "(net amount at risk re-measured on the post-interest value).",
            "timing_step", [], _coi_step_middle,
        ),
        _switch(
            "coi.timing.end", "coi", "COI deducted at the end of the month",
            "Fees are deducted and interest credited first; the COI charge is "
            "measured on the post-interest account value and deducted last.",
            "timing_step", [], _coi_step_end,
        ),
        _switch(
            "coi.placeholder.flat_face", "coi", "Placeholder COI (flat rate on face)",
            "Used only when no COI schedule is in force: a flat annual rate on "
            "the face amount, divided by 12 each month. It is not a rate x net "
            "amount at risk and is labelled a placeholder wherever it appears.",
            "placeholder",
            [ParamSpec("flatRate", "number", "Flat annual placeholder rate", minimum=0)],
            coi_placeholder_monthly_charge,
        ),
        _switch(
            "coi.schedule.banded", "coi", "Banded COI schedule",
            "A COI schedule stated as duration bands: each band sets the rate "
            "(constant within the band, or grading linearly to the band's end "
            "value) for its years. Materialises into one validated COI row "
            "per duration, each stamped with the band it came from.",
            "schedule_materializer",
            [ParamSpec("bands", "bands", "Duration bands")],
            materialize_banded_rows,
        ),
        # --- NAR definitions ----------------------------------------------
        _switch(
            "nar.definition.factor_adjusted", "nar_factors", "NAR with the filed factor applied",
            "Net amount at risk = death benefit / NAR factor - account value. "
            "This is the standard filed definition when the product states a "
            "net amount at risk factor.",
            "nar_definition", [], _nar_factor_adjusted,
        ),
        _switch(
            "nar.definition.unadjusted", "nar_factors", "NAR without the factor",
            "Net amount at risk = death benefit - account value. The filed NAR "
            "factor, if any, is not applied (it stays on the record so the "
            "derivation can show both).",
            "nar_definition", [], _nar_unadjusted,
        ),
        # --- Surrender bases ------------------------------------------------
        _switch(
            "surrender.basis.percent_account_value", "surrender",
            "Surrender charge as a percentage of account value",
            "Surrender charge = the schedule percentage x the ending account value.",
            "surrender_basis", [_CHARGE_PARAM], _surrender_percent_account_value,
        ),
        _switch(
            "surrender.basis.percent_face", "surrender",
            "Surrender charge as a percentage of face amount",
            "Surrender charge = the schedule percentage x the face amount, "
            "exactly as a schedule on that basis states it.",
            "surrender_basis", [_CHARGE_PARAM], _surrender_percent_face,
        ),
        _switch(
            "surrender.basis.per_1000_face", "surrender",
            "Surrender charge per $1,000 of face amount",
            "Surrender charge = (face amount / 1,000) x the schedule charge "
            "per $1,000 of face amount.",
            "surrender_basis", [_CHARGE_PARAM], _surrender_per_1000_face,
        ),
        _switch(
            "surrender.basis.fixed", "surrender", "Fixed surrender charge",
            "Surrender charge = the fixed amount stated in the schedule for "
            "this duration.",
            "surrender_basis", [_CHARGE_PARAM], _surrender_fixed,
        ),
        _switch(
            "surrender.schedule.graded", "surrender", "Graded surrender schedule",
            "A surrender schedule that starts at a stated value in year 1 and "
            "grades linearly to zero at the end of the grading period, on a "
            "percentage-of-account-value, percentage-of-face, or flat basis.",
            "schedule_materializer",
            [
                ParamSpec("basis", "choice", "Schedule basis",
                          choices=("percent_account_value", "percent_face", "flat_amount")),
                ParamSpec("percent", "number", "Starting percentage",
                          required=False, minimum=0, maximum=1),
                ParamSpec("amount", "number", "Starting flat amount", required=False, minimum=0),
                ParamSpec("gradingYears", "integer", "Years grading to zero",
                          minimum=1, maximum=40),
            ],
            materialize_graded_surrender,
        ),
        _switch(
            "surrender.schedule.banded", "surrender", "Banded surrender schedule",
            "A surrender schedule stated as duration bands (Eddy's piecewise "
            "case): each band sets the charge — on any surrender basis, "
            "constant within the band or grading linearly to the band's end "
            "value — for its years. Materialises into one validated row per "
            "duration, each stamped with the band it came from.",
            "schedule_materializer",
            [ParamSpec("bands", "bands", "Duration bands")],
            materialize_banded_rows,
        ),
        _switch(
            "surrender.placeholder.linear_account_value", "surrender",
            "Placeholder surrender charge (declining percentage of account value)",
            "Used only when no surrender schedule is in force: a percentage of "
            "the ending account value declining linearly to zero over the "
            "surrender period. Labelled a placeholder wherever it appears.",
            "placeholder",
            [
                ParamSpec("periodYears", "integer", "Surrender period (years)", minimum=1),
                ParamSpec("maxPct", "number", "Year-1 placeholder percentage",
                          minimum=0, maximum=1),
            ],
            surrender_placeholder_charge,
        ),
        # --- Fees -----------------------------------------------------------
        _switch(
            "fees.unit.monthly_fixed", "fees", "Monthly fixed fee",
            "The stated amount is deducted every month.",
            "fee_unit", [_AMOUNT_PARAM], _fee_monthly_fixed,
        ),
        _switch(
            "fees.unit.modal_fixed", "fees", "Modal fixed fee",
            "The stated amount is deducted in months a premium payment is due.",
            "fee_unit", [_AMOUNT_PARAM], _fee_modal_fixed,
        ),
        _switch(
            "fees.unit.per_1000_face_annual", "fees", "Annual fee per $1,000 of face",
            "Each month: fee = (face amount / 1,000) x the annual amount / 12.",
            "fee_unit", [_AMOUNT_PARAM], _fee_per_1000_face_annual,
        ),
        _switch(
            "fees.unit.annual_fixed", "fees", "Annual fixed fee",
            "The stated annual amount is spread evenly: amount / 12 each month.",
            "fee_unit", [_AMOUNT_PARAM], _fee_annual_fixed,
        ),
        _switch(
            "fees.unit.percent_premium", "fees", "Premium expense charge (percentage of premium)",
            "A percentage of each premium payment, deducted from the payment "
            "before it is added to the account value (a premium load). It is "
            "never also deducted as a monthly fee.",
            "fee_unit", [_AMOUNT_PARAM], _fee_percent_premium_monthly,
        ),
        _switch(
            "fees.fallback.configured_annual", "fees", "Fallback fee (configured annual amount)",
            "Used only when no fee schedule is in force: the configured annual "
            "policy/admin fee spread evenly over the months. Labelled a "
            "fallback wherever it appears.",
            "placeholder",
            [ParamSpec("annualFee", "number", "Configured annual fee", minimum=0)],
            fee_fallback_monthly,
        ),
        # --- Crediting -------------------------------------------------------
        _switch(
            "crediting.guaranteed_annual", "crediting", "Guaranteed annual credited rate",
            "Interest is credited monthly at the guaranteed annual rate: "
            "monthly rate = (1 + annual rate)^(1/12) - 1, on the account value "
            "after premiums, premium loads, COI and fees.",
            "crediting",
            [ParamSpec("guaranteedRate", "number", "Guaranteed annual credited rate")],
            _monthly_rate_from_annual,
        ),
    ]
}

#: Row-unit -> bank switch id, for the units the row validators admit.
COI_RATE_SWITCH_BY_UNIT: Dict[str, str] = {
    "per_1000_monthly": "coi.rate.per_1000_monthly",
    "per_1000_annual": "coi.rate.per_1000_annual",
    "percent_nar_annual": "coi.rate.percent_nar_annual",
}
SURRENDER_SWITCH_BY_UNIT: Dict[str, str] = {
    "percent_account_value": "surrender.basis.percent_account_value",
    "percent_face": "surrender.basis.percent_face",
    "per_1000_face": "surrender.basis.per_1000_face",
    "fixed": "surrender.basis.fixed",
}
FEE_SWITCH_BY_UNIT: Dict[str, str] = {
    "monthly_fixed": "fees.unit.monthly_fixed",
    "modal_fixed": "fees.unit.modal_fixed",
    "per_1000_face_annual": "fees.unit.per_1000_face_annual",
    "annual_fixed": "fees.unit.annual_fixed",
    "percent_premium": "fees.unit.percent_premium",
}
COI_TIMING_SWITCHES: Dict[str, str] = {
    timing: f"coi.timing.{timing}" for timing in ("beginning", "middle", "end")
}
NAR_DEFINITION_SWITCHES: Dict[str, str] = {
    definition: f"nar.definition.{definition}"
    for definition in ("factor_adjusted", "unadjusted")
}


def get_switch(switch_id: str) -> BankedSwitch:
    """Look up a banked switch by id; an unbanked id is an error."""

    try:
        return SWITCHES[switch_id]
    except KeyError:
        raise ValueError(f"No banked switch with id {switch_id!r}") from None


def all_switches() -> List[BankedSwitch]:
    return [SWITCHES[key] for key in sorted(SWITCHES)]


def switches_for_mechanic(mechanic: str) -> List[BankedSwitch]:
    return [switch for switch in all_switches() if switch.mechanic == mechanic]


def bank_catalog() -> List[Dict[str, Any]]:
    """The full registry as JSON-safe views (API / governance display)."""

    return [switch.view() for switch in all_switches()]


# ---------------------------------------------------------------------------
# Engine dispatch helpers
#
# The projection loop calls these — never raw formulas — for every
# mechanic the bank covers.  An unbanked unit raises: the engine does
# not improvise a meaning for a value the bank does not know.
# ---------------------------------------------------------------------------


def coi_rate_switch_id(unit: str) -> str:
    try:
        return COI_RATE_SWITCH_BY_UNIT[unit]
    except KeyError:
        raise ValueError(f"Unbanked COI rate unit: {unit!r}") from None


def coi_charge_for_unit(unit: str, rate: float, nar: float) -> float:
    return get_switch(coi_rate_switch_id(unit)).implementation(rate, nar)


def nar_switch_id(definition: str) -> str:
    try:
        return NAR_DEFINITION_SWITCHES[definition]
    except KeyError:
        raise ValueError(f"Unbanked NAR definition: {definition!r}") from None


def coi_nar_for_definition(
    definition: str, death_benefit: float, value: float, factor: float
) -> float:
    return get_switch(nar_switch_id(definition)).implementation(death_benefit, value, factor)


def coi_timing_switch_id(timing: str) -> str:
    try:
        return COI_TIMING_SWITCHES[timing]
    except KeyError:
        raise ValueError(f"Unbanked COI timing: {timing!r}") from None


def coi_step_for_timing(timing: str, value, monthly_fee, interest_rate, month_coi, track_nar):
    """Run one month of COI sequencing under a banked timing switch."""

    step = get_switch(coi_timing_switch_id(timing)).implementation
    return step(value, monthly_fee, interest_rate, month_coi, track_nar)


def surrender_switch_id(unit: str) -> str:
    try:
        return SURRENDER_SWITCH_BY_UNIT[unit]
    except KeyError:
        raise ValueError(f"Unbanked surrender charge unit: {unit!r}") from None


def surrender_charge_for_unit(
    unit: str, charge: float, policy_value: float, face_amount: float
) -> float:
    return get_switch(surrender_switch_id(unit)).implementation(charge, policy_value, face_amount)


def fee_switch_id(unit: str) -> str:
    try:
        return FEE_SWITCH_BY_UNIT[unit]
    except KeyError:
        raise ValueError(f"Unbanked fee unit: {unit!r}") from None


def monthly_fee_for_unit(
    unit: str, amount: float, *, face_amount: float, payment_due: bool
) -> float:
    impl = get_switch(fee_switch_id(unit)).implementation
    return impl(amount, face_amount=face_amount, payment_due=payment_due)


def monthly_crediting_rate(annual_rate: float) -> float:
    return get_switch("crediting.guaranteed_annual").implementation(annual_rate)


__all__ = [
    "BAND_UNITS",
    "COI_RATE_SWITCH_BY_UNIT",
    "COI_TIMING_SWITCHES",
    "FEE_SWITCH_BY_UNIT",
    "MAX_SCHEDULE_DURATION",
    "NAR_DEFINITION_SWITCHES",
    "SURRENDER_SWITCH_BY_UNIT",
    "SWITCHES",
    "BankedSwitch",
    "ParamSpec",
    "all_switches",
    "bank_catalog",
    "coi_charge_for_unit",
    "coi_nar_for_definition",
    "coi_placeholder_monthly_charge",
    "coi_rate_switch_id",
    "coi_step_for_timing",
    "coi_timing_switch_id",
    "fee_fallback_monthly",
    "fee_switch_id",
    "get_switch",
    "materialize_banded_rows",
    "materialize_graded_surrender",
    "monthly_crediting_rate",
    "monthly_fee_for_unit",
    "nar_switch_id",
    "premium_load_for_row",
    "surrender_charge_for_unit",
    "surrender_placeholder_charge",
    "surrender_switch_id",
    "switches_for_mechanic",
    "validate_bands",
    "validate_params",
]
