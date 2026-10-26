"""Phase 7 (the Equation Doctrine): the formula language.

The only equations the projection engine executes are the ones stored
as artifacts on a workspace — document-derived and human-approved, or
actuary-authored in the product — plus the universal identities that
live in the projection skeleton itself (see
``docs/phase-7-equations.md``).  This module is the language those
artifacts are written in:

* a constrained, deterministic AST (JSON) — arithmetic, min/max,
  duration-banded conditionals, table lookups over the workspace's
  accepted tables, and the chassis quantities.  There is no ``eval``,
  no expression strings, no generated code anywhere in the pipeline;
* a validator that rejects an invalid equation at approval time with
  a specific message (unknown quantity for the mechanic's context,
  unknown table/field, type error, malformed bands);
* an evaluator — a small deterministic interpreter.  A runtime defect
  (lookup miss with no default, division by zero, an uncovered band)
  raises :class:`Unevaluable`; the caller treats the mechanic as not
  calculated for that period and flags the run incomplete;
* a canonical plain-language renderer.  The rendering is derived from
  the AST by exactly one code path, and it is what the approval screen
  shows beside the filing's verbatim words and what the ledger cites —
  the formula printed is the equation that ran.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Mechanics, tables, quantities
# ---------------------------------------------------------------------------

#: The mechanics an equation artifact can govern, in product order.
MECHANICS: Tuple[str, ...] = (
    "coi_charge",
    "surrender_charge",
    "premium_load",
    "policy_fees",
    "crediting",
    "nar_definition",
    "death_benefit",
)

MECHANIC_LABELS: Dict[str, str] = {
    "coi_charge": "COI charge",
    "surrender_charge": "Surrender charge",
    "premium_load": "Premium load",
    "policy_fees": "Policy and admin fees",
    "crediting": "Interest crediting",
    "nar_definition": "Net amount at risk definition",
    "death_benefit": "Death benefit",
}

#: Table name -> (mechanics-artifact key, value field, unit field).
TABLES: Dict[str, Tuple[str, str, Optional[str]]] = {
    "coi": ("coi", "rate", "rate_unit"),
    "surrender": ("surrender", "charge", "charge_unit"),
    "fees": ("fees", "amount", "fee_unit"),
    "nar_factors": ("nar_factors", "factor", None),
    "corridor": ("corridor", "percentage", None),
}

TABLE_LABELS: Dict[str, str] = {
    "coi": "COI table",
    "surrender": "surrender schedule",
    "fees": "fee schedule",
    "nar_factors": "NAR factor table",
    "corridor": "corridor table",
}

#: Row fields a lookup/rows_sum ``where`` filter may test.
ROW_FILTER_FIELDS = {
    "component", "fee_unit", "rate_unit", "charge_unit", "duration",
    "attained_age", "sex", "risk_class", "tobacco_status", "issue_age",
    "premium_mode",
}

#: Quantities every mechanic's context carries.
COMMON_QUANTITIES: Dict[str, str] = {
    "duration": "number",
    "month_in_year": "number",
    "attained_age": "number",
    "issue_age": "number",
    "face_amount": "number",
    "premium_due": "number",
    "payment_due": "number",
    "guaranteed_rate": "number",
}

#: Extra quantities per mechanic (beyond the common set).
MECHANIC_QUANTITIES: Dict[str, Dict[str, str]] = {
    "coi_charge": {
        "account_value": "number",
        "death_benefit": "number",
        "nar": "number",
    },
    "surrender_charge": {"account_value": "number"},
    "premium_load": {},
    "policy_fees": {"account_value": "number"},
    "crediting": {"account_value": "number"},
    "nar_definition": {
        "account_value": "number",
        "death_benefit": "number",
    },
    "death_benefit": {"account_value": "number"},
}

#: Quantities bound per row inside a ``rows_sum`` expression.
ROW_QUANTITIES: Dict[str, str] = {"row_amount": "number", "row_unit": "string"}

QUANTITY_LABELS: Dict[str, str] = {
    "duration": "the policy duration",
    "month_in_year": "the month of the policy year",
    "attained_age": "the attained age",
    "issue_age": "the issue age",
    "face_amount": "the face amount",
    "account_value": "the account value",
    "death_benefit": "the death benefit",
    "nar": "the net amount at risk",
    "premium_due": "the premium due this month",
    "payment_due": "whether a premium is due this month",
    "guaranteed_rate": "the guaranteed annual rate",
    "row_amount": "the row amount",
    "row_unit": "the row unit",
}

#: COI deduction timings (an attribute of the coi_charge artifact).
COI_TIMINGS: Tuple[str, ...] = ("beginning", "middle", "end")

#: Ledger basis per equation source kind (see projection_ledger).
BASIS_BY_SOURCE_KIND: Dict[str, str] = {
    "document": "filed",
    "correction": "corrected",
    "proposal": "filed",
    "actuary": "equation",
    "specimen": "equation",
    "pre_doctrine_migration": "equation",
}

TIMING_SENTENCES: Dict[str, str] = {
    "beginning": (
        "The COI charge is deducted at the beginning of each month, "
        "before interest is credited."
    ),
    "middle": (
        "The COI charge is deducted in the middle of each month: half "
        "before interest is credited and half after."
    ),
    "end": (
        "The COI charge is deducted at the end of each month, after "
        "interest is credited."
    ),
}


class Unevaluable(Exception):
    """The equation cannot produce a value in this context.

    Raised for lookup misses with no default, division by zero, bands
    that do not cover the duration, and non-finite results.  The
    projection loop treats the mechanic as not calculated for the
    period and flags the run incomplete with this reason.
    """


def quantities_for(mechanic: str) -> Dict[str, str]:
    """The quantity -> type map available to one mechanic's equation."""

    merged = dict(COMMON_QUANTITIES)
    merged.update(MECHANIC_QUANTITIES.get(mechanic) or {})
    return merged


# ---------------------------------------------------------------------------
# Row selection — the lookup addressing contract.
#
# One implementation, shared by the evaluator and the projection loop:
# a row matches when every selector it specifies equals the context
# (unspecified = matches all); among matches the most specific wins.
# ---------------------------------------------------------------------------

_SELECTOR_FIELDS = (
    "duration", "attained_age", "sex", "risk_class", "tobacco_status",
    "issue_age", "premium_mode",
)


def _row_matches(row: Mapping[str, Any], field: str, actual: Any) -> bool:
    expected = row.get(field)
    return expected in {None, "", "ANY", "All"} or (
        actual is not None
        and str(expected).strip().lower() == str(actual).strip().lower()
    )


def select_rows(
    rows: Sequence[Mapping[str, Any]], values: Mapping[str, Any]
) -> List[Mapping[str, Any]]:
    """Every row of ``rows`` selected by the context ``values``."""

    return [
        row for row in rows
        if (row.get("duration") in {None, values.get("duration")})
        and (row.get("attained_age") in {None, values.get("attained_age")})
        and _row_matches(row, "sex", values.get("sex"))
        and _row_matches(row, "risk_class", values.get("risk_class"))
        and _row_matches(row, "tobacco_status", values.get("tobacco_status"))
        and _row_matches(row, "issue_age", values.get("issue_age"))
        and _row_matches(row, "premium_mode", values.get("premium_mode"))
    ]


def select_row(
    rows: Sequence[Mapping[str, Any]], values: Mapping[str, Any]
) -> Optional[Mapping[str, Any]]:
    """The most specific selected row, or None."""

    candidates = select_rows(rows, values)
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: sum(
            row.get(field) not in {None, "", "ANY", "All"}
            for field in _SELECTOR_FIELDS
        ),
        reverse=True,
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# Validation — run at approval/authoring time, never first at run time.
# ---------------------------------------------------------------------------

_ARITHMETIC_NODES = {"add", "sub", "mul", "div", "neg", "min", "max", "pow"}
_COMPARISON_OPS = {"<", "<=", ">", ">=", "==", "!="}


def validate_equation(mechanic: str, body: Any) -> List[str]:
    """Validate an equation body for ``mechanic``; [] means valid.

    Every defect is reported with a specific message — approval must be
    able to say exactly what is wrong, because an actuary is being
    asked to put their name on this equation.
    """

    if mechanic not in MECHANICS:
        return [f"Unknown mechanic: {mechanic!r}"]
    if not isinstance(body, dict) or not body:
        return ["The equation body must be a single formula node (a JSON object)"]
    errors: List[str] = []
    result_type = _validate_node(
        mechanic, body, quantities_for(mechanic), errors, in_rows_sum=False
    )
    if result_type is not None and result_type != "number":
        errors.append(
            f"The equation must produce a number, not a {result_type}"
        )
    return errors


def _node_key(node: Any, errors: List[str]) -> Optional[str]:
    if not isinstance(node, dict) or len(node) != 1:
        errors.append(
            "Each formula node must be an object with exactly one operator key"
        )
        return None
    return next(iter(node))


def _validate_operands(
    mechanic: str,
    operands: Any,
    quantities: Mapping[str, str],
    errors: List[str],
    *,
    in_rows_sum: bool,
    count: Optional[Tuple[int, Optional[int]]] = None,
) -> List[Optional[str]]:
    if not isinstance(operands, list) or not operands:
        errors.append("An operator needs a non-empty list of operands")
        return []
    if count is not None:
        low, high = count
        if len(operands) < low or (high is not None and len(operands) > high):
            errors.append(
                f"This operator takes {'exactly ' if low == high else 'at least '}"
                f"{low} operand(s); got {len(operands)}"
            )
    return [
        _validate_node(mechanic, operand, quantities, errors, in_rows_sum=in_rows_sum)
        for operand in operands
    ]


def _require_numbers(
    label: str, types: Sequence[Optional[str]], errors: List[str]
) -> None:
    for operand_type in types:
        if operand_type is not None and operand_type != "number":
            errors.append(f"{label} operands must be numbers, not {operand_type}s")
            return


def _validate_node(
    mechanic: str,
    node: Any,
    quantities: Mapping[str, str],
    errors: List[str],
    *,
    in_rows_sum: bool,
) -> Optional[str]:
    """Return the node's type ("number" | "string" | "bool") or None."""

    key = _node_key(node, errors)
    if key is None:
        return None
    value = node[key]

    if key == "const":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("A const node must carry a number")
            return None
        if not math.isfinite(float(value)):
            errors.append("A const node must be a finite number")
            return None
        return "number"
    if key == "str":
        if not isinstance(value, str):
            errors.append("A str node must carry a string")
            return None
        return "string"
    if key == "qty":
        if not isinstance(value, str):
            errors.append("A qty node must name a quantity")
            return None
        if value in ROW_QUANTITIES:
            if not in_rows_sum:
                errors.append(
                    f"Quantity {value!r} is only available inside a rows_sum expression"
                )
                return None
            return ROW_QUANTITIES[value]
        if value not in quantities:
            errors.append(
                f"Unknown quantity {value!r} for the {MECHANIC_LABELS[mechanic]} "
                f"equation (available: {', '.join(sorted(quantities))})"
            )
            return None
        return quantities[value]
    if key in _ARITHMETIC_NODES:
        counts = {"sub": (2, 2), "div": (2, 2), "neg": (1, 1), "pow": (2, 2)}
        types = _validate_operands(
            mechanic, value, quantities, errors,
            in_rows_sum=in_rows_sum, count=counts.get(key),
        )
        _require_numbers(f"The '{key}' operator's", types, errors)
        return "number"
    if key == "if":
        if not isinstance(value, dict) or set(value) != {"cond", "then", "else"}:
            errors.append("An if node needs exactly cond, then, and else")
            return None
        cond_type = _validate_node(
            mechanic, value["cond"], quantities, errors, in_rows_sum=in_rows_sum
        )
        if cond_type is not None and cond_type != "bool":
            errors.append("An if condition must be a comparison or a logical combination")
        then_type = _validate_node(
            mechanic, value["then"], quantities, errors, in_rows_sum=in_rows_sum
        )
        else_type = _validate_node(
            mechanic, value["else"], quantities, errors, in_rows_sum=in_rows_sum
        )
        if then_type is not None and else_type is not None and then_type != else_type:
            errors.append("The then and else branches of an if must have the same type")
        return then_type
    if key == "cmp":
        if not isinstance(value, list) or len(value) != 3:
            errors.append("A cmp node is [operator, left, right]")
            return None
        op, left, right = value
        if op not in _COMPARISON_OPS:
            errors.append(f"Unknown comparison operator: {op!r}")
            return None
        left_type = _validate_node(
            mechanic, left, quantities, errors, in_rows_sum=in_rows_sum
        )
        right_type = _validate_node(
            mechanic, right, quantities, errors, in_rows_sum=in_rows_sum
        )
        if left_type is not None and right_type is not None:
            if left_type != right_type:
                errors.append(
                    f"A comparison needs both sides to be the same type "
                    f"(got {left_type} and {right_type})"
                )
            elif left_type == "string" and op not in {"==", "!="}:
                errors.append("Strings can only be compared with == or !=")
            elif left_type == "bool":
                errors.append("Conditions cannot be compared")
        return "bool"
    if key in {"and", "or"}:
        types = _validate_operands(
            mechanic, value, quantities, errors, in_rows_sum=in_rows_sum
        )
        for operand_type in types:
            if operand_type is not None and operand_type != "bool":
                errors.append(f"'{key}' operands must be conditions")
                break
        return "bool"
    if key == "not":
        operand_type = _validate_node(
            mechanic, value, quantities, errors, in_rows_sum=in_rows_sum
        )
        if operand_type is not None and operand_type != "bool":
            errors.append("'not' needs a condition operand")
        return "bool"
    if key == "bands":
        return _validate_bands(mechanic, value, quantities, errors, in_rows_sum)
    if key == "lookup":
        return _validate_lookup(mechanic, value, quantities, errors, in_rows_sum)
    if key == "rows_sum":
        if in_rows_sum:
            errors.append("A rows_sum cannot be nested inside another rows_sum")
            return None
        return _validate_rows_sum(mechanic, value, quantities, errors)
    errors.append(f"Unknown formula node: {key!r}")
    return None


def _validate_bands(
    mechanic: str, value: Any, quantities: Mapping[str, str],
    errors: List[str], in_rows_sum: bool,
) -> Optional[str]:
    if not isinstance(value, list) or not value:
        errors.append("A bands node needs a non-empty list of bands")
        return None
    previous_to: Optional[int] = None
    for index, band in enumerate(value):
        if not isinstance(band, dict) or not {"from", "to", "value"} <= set(band):
            errors.append(f"Band {index + 1} needs from, to, and value")
            continue
        start, end = band.get("from"), band.get("to")
        if isinstance(start, bool) or not isinstance(start, int) or start < 1:
            errors.append(f"Band {index + 1}: 'from' must be a policy year >= 1")
            continue
        if end is not None and (
            isinstance(end, bool) or not isinstance(end, int) or end < start
        ):
            errors.append(f"Band {index + 1}: 'to' must be a policy year >= 'from', or null")
            continue
        if previous_to is not None and start <= previous_to:
            errors.append(
                f"Band {index + 1} overlaps or is out of order "
                f"(previous band ends at year {previous_to})"
            )
        previous_to = end if end is not None else 10 ** 9
        band_type = _validate_node(
            mechanic, band.get("value"), quantities, errors, in_rows_sum=in_rows_sum
        )
        if band_type is not None and band_type != "number":
            errors.append(f"Band {index + 1}'s value must be a number")
    return "number"


def _validate_where(where: Any, errors: List[str], label: str) -> None:
    if where is None:
        return
    if not isinstance(where, dict):
        errors.append(f"{label}: 'where' must be an object of row-field filters")
        return
    for field, expected in where.items():
        if field not in ROW_FILTER_FIELDS:
            errors.append(
                f"{label}: cannot filter on row field {field!r} "
                f"(filterable: {', '.join(sorted(ROW_FILTER_FIELDS))})"
            )
        elif not isinstance(expected, (str, int, float)) or isinstance(expected, bool):
            errors.append(f"{label}: filter value for {field!r} must be a string or number")


def _validate_lookup(
    mechanic: str, value: Any, quantities: Mapping[str, str],
    errors: List[str], in_rows_sum: bool,
) -> Optional[str]:
    if not isinstance(value, dict) or "table" not in value:
        errors.append("A lookup node needs a table")
        return None
    table = value.get("table")
    if table not in TABLES:
        errors.append(
            f"Unknown table {table!r} (available: {', '.join(sorted(TABLES))})"
        )
        return None
    _key, field, _unit = TABLES[str(table)]
    if "field" in value and value["field"] != field:
        errors.append(
            f"The {table} table's value field is {field!r}, not {value['field']!r}"
        )
    _validate_where(value.get("where"), errors, f"Lookup on {table}")
    if "default" in value and value["default"] is not None:
        default_type = _validate_node(
            mechanic, value["default"], quantities, errors, in_rows_sum=in_rows_sum
        )
        if default_type is not None and default_type != "number":
            errors.append("A lookup default must be a number expression")
    return "number"


def _validate_rows_sum(
    mechanic: str, value: Any, quantities: Mapping[str, str], errors: List[str]
) -> Optional[str]:
    if not isinstance(value, dict) or "table" not in value or "expr" not in value:
        errors.append("A rows_sum node needs a table and an expr")
        return None
    table = value.get("table")
    if table not in TABLES:
        errors.append(
            f"Unknown table {table!r} (available: {', '.join(sorted(TABLES))})"
        )
        return None
    _validate_where(value.get("where"), errors, f"rows_sum on {table}")
    _validate_where(value.get("exclude_where"), errors, f"rows_sum on {table}")
    expr_type = _validate_node(
        mechanic, value["expr"], quantities, errors, in_rows_sum=True
    )
    if expr_type is not None and expr_type != "number":
        errors.append("A rows_sum expression must produce a number per row")
    return "number"


# ---------------------------------------------------------------------------
# Evaluation — a deterministic interpreter over a validated AST.
#
# ``values`` carries the quantities plus the row-selection context
# (sex, risk_class, tobacco_status, premium_mode as strings);
# ``tables`` maps table name -> the workspace's accepted rows.
# ---------------------------------------------------------------------------


def evaluate(
    body: Mapping[str, Any],
    values: Mapping[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
) -> float:
    """Evaluate a validated equation body to a number.

    Raises :class:`Unevaluable` when the equation cannot produce a
    value in this context (lookup miss with no default, division by
    zero, an uncovered band, a non-finite result).
    """

    result = _eval_node(body, dict(values), tables)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise Unevaluable("the equation did not produce a number")
    if not math.isfinite(float(result)):
        raise Unevaluable("the equation produced a non-finite result")
    return float(result)


def _where_matches(row: Mapping[str, Any], where: Optional[Mapping[str, Any]]) -> bool:
    if not where:
        return True
    for field, expected in where.items():
        actual = row.get(field)
        if actual is None:
            return False
        if isinstance(expected, str):
            if str(actual).strip().lower() != expected.strip().lower():
                return False
        elif float(actual) != float(expected):
            return False
    return True


def _table_rows(
    tables: Mapping[str, Sequence[Mapping[str, Any]]], table: str
) -> List[Mapping[str, Any]]:
    return list(tables.get(table) or [])


def _eval_node(
    node: Mapping[str, Any],
    values: Dict[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Any:
    key = next(iter(node))
    value = node[key]

    if key == "const":
        return float(value)
    if key == "str":
        return str(value)
    if key == "qty":
        if value not in values:
            raise Unevaluable(f"quantity {value!r} has no value in this context")
        return values[value]
    if key in _ARITHMETIC_NODES:
        operands = [_eval_node(item, values, tables) for item in _operand_list(value)]
        if key == "add":
            return sum(operands)
        if key == "mul":
            result = 1.0
            for operand in operands:
                result *= operand
            return result
        if key == "min":
            return min(operands)
        if key == "max":
            return max(operands)
        if key == "sub":
            return operands[0] - operands[1]
        if key == "neg":
            return -operands[0]
        if key == "div":
            if operands[1] == 0:
                raise Unevaluable("division by zero")
            return operands[0] / operands[1]
        if key == "pow":
            try:
                return math.pow(operands[0], operands[1])
            except (ValueError, OverflowError) as exc:
                raise Unevaluable(f"power is not defined here ({exc})") from exc
    if key == "if":
        branch = value["then"] if _eval_node(value["cond"], values, tables) else value["else"]
        return _eval_node(branch, values, tables)
    if key == "cmp":
        op, left_node, right_node = value
        left = _eval_node(left_node, values, tables)
        right = _eval_node(right_node, values, tables)
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "==":
            return left == right
        return left != right
    if key == "and":
        return all(_eval_node(item, values, tables) for item in value)
    if key == "or":
        return any(_eval_node(item, values, tables) for item in value)
    if key == "not":
        return not _eval_node(value, values, tables)
    if key == "bands":
        duration = values.get("duration")
        for band in value:
            start, end = band["from"], band["to"]
            if duration is not None and start <= duration and (end is None or duration <= end):
                return _eval_node(band["value"], values, tables)
        raise Unevaluable(f"no band covers duration {duration}")
    if key == "lookup":
        return _eval_lookup(value, values, tables)
    if key == "rows_sum":
        return _eval_rows_sum(value, values, tables)
    raise Unevaluable(f"unknown formula node {key!r}")


def _operand_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else [value]


def _eval_lookup(
    spec: Mapping[str, Any],
    values: Dict[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
) -> float:
    table = str(spec["table"])
    _key, field, _unit = TABLES[table]
    rows = [
        row for row in _table_rows(tables, table)
        if _where_matches(row, spec.get("where"))
    ]
    row = select_row(rows, values)
    if row is None or row.get(field) is None:
        if spec.get("default") is not None:
            return float(_eval_node(spec["default"], values, tables))
        raise Unevaluable(
            f"no {TABLE_LABELS[table]} row applies at duration "
            f"{values.get('duration')}, attained age {values.get('attained_age')}"
        )
    return float(row[field])


def _eval_rows_sum(
    spec: Mapping[str, Any],
    values: Dict[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
) -> float:
    table = str(spec["table"])
    _key, field, unit_field = TABLES[table]
    rows = select_rows(_table_rows(tables, table), values)
    total = 0.0
    for row in rows:
        if not _where_matches(row, spec.get("where")):
            continue
        if spec.get("exclude_where") and _where_matches(row, spec["exclude_where"]):
            continue
        row_values = dict(values)
        amount = row.get(field)
        row_values["row_amount"] = float(amount) if amount is not None else 0.0
        row_values["row_unit"] = str(row.get(unit_field) or "") if unit_field else ""
        total += float(_eval_node(spec["expr"], row_values, tables))
    return total


# ---------------------------------------------------------------------------
# Canonical rendering — the one plain-language form of an equation.
#
# Deterministic from the AST.  This is the text approval shows beside
# the filing's verbatim words and the text the ledger cites.
# ---------------------------------------------------------------------------

_PRECEDENCE = {"add": 1, "sub": 1, "mul": 2, "div": 2, "neg": 3, "pow": 3}
_CMP_SYMBOLS = {"<": "<", "<=": "≤", ">": ">", ">=": "≥", "==": "=", "!=": "≠"}


def _fmt_num(value: Any) -> str:
    number = float(value)
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.10g}"


#: Per-mechanic quantity label overrides: in the surrender context the
#: account value the equation sees is the year-end (ending) value.
MECHANIC_QUANTITY_LABELS: Dict[str, Dict[str, str]] = {
    "surrender_charge": {"account_value": "the ending account value"},
}


def render_equation(body: Mapping[str, Any], mechanic: Optional[str] = None) -> str:
    """The canonical plain-language rendering of an equation body."""

    labels = dict(QUANTITY_LABELS)
    if mechanic:
        labels.update(MECHANIC_QUANTITY_LABELS.get(mechanic) or {})
    return _render_node(body, parent_precedence=0, labels=labels)


def render_with_timing(body: Mapping[str, Any], timing: Optional[str]) -> str:
    """The rendering of a coi_charge equation, timing sentence included."""

    text = render_equation(body, mechanic="coi_charge")
    if timing in TIMING_SENTENCES:
        text = f"{text} {TIMING_SENTENCES[str(timing)]}"
    return text


def _render_node(node: Mapping[str, Any], parent_precedence: int, labels: Optional[Dict[str, str]] = None) -> str:
    labels = labels or QUANTITY_LABELS
    key = next(iter(node))
    value = node[key]

    if key == "const":
        return _fmt_num(value)
    if key == "str":
        return f'"{value}"'
    if key == "qty":
        return labels.get(str(value), str(value).replace("_", " "))
    if key in _PRECEDENCE:
        precedence = _PRECEDENCE[key]
        if key == "add":
            text = " + ".join(_render_node(item, precedence, labels) for item in value)
        elif key == "mul":
            text = " × ".join(_render_node(item, precedence, labels) for item in value)
        elif key == "sub":
            text = (
                f"{_render_node(value[0], precedence, labels)} − "
                f"{_render_node(value[1], precedence + 1, labels)}"
            )
        elif key == "div":
            text = (
                f"{_render_node(value[0], precedence, labels)} / "
                f"{_render_node(value[1], precedence + 1, labels)}"
            )
        elif key == "neg":
            text = f"−{_render_node(value, precedence, labels)}"
        else:  # pow
            text = (
                f"{_render_node(value[0], precedence + 1, labels)} ^ "
                f"{_render_node(value[1], precedence + 1, labels)}"
            )
        return f"({text})" if precedence < parent_precedence else text
    if key == "min":
        return "the lesser of (" + ", ".join(
            _render_node(item, 0, labels) for item in value
        ) + ")"
    if key == "max":
        return "the greater of (" + ", ".join(
            _render_node(item, 0, labels) for item in value
        ) + ")"
    if key == "if":
        return (
            f"if {_render_node(value['cond'], 0, labels)}, then "
            f"{_render_node(value['then'], 0, labels)}; otherwise "
            f"{_render_node(value['else'], 0, labels)}"
        )
    if key == "cmp":
        op, left, right = value
        return (
            f"{_render_node(left, 0, labels)} {_CMP_SYMBOLS.get(str(op), str(op))} "
            f"{_render_node(right, 0, labels)}"
        )
    if key == "and":
        return " and ".join(_render_node(item, 0, labels) for item in value)
    if key == "or":
        return " or ".join(_render_node(item, 0, labels) for item in value)
    if key == "not":
        return f"not ({_render_node(value, 0, labels)})"
    if key == "bands":
        parts = []
        for band in value:
            start, end = band["from"], band["to"]
            span = f"year {start}" if end == start else (
                f"years {start} and later" if end is None else f"years {start}–{end}"
            )
            parts.append(f"{span}: {_render_node(band['value'], 0, labels)}")
        return "by policy duration — " + "; ".join(parts)
    if key == "lookup":
        return _render_lookup(value, labels)
    if key == "rows_sum":
        return _render_rows_sum(value, labels)
    return f"<{key}>"


def _render_where(where: Optional[Mapping[str, Any]]) -> str:
    if not where:
        return ""
    parts = [
        f"{field.replace('_', ' ')}: {expected}"
        for field, expected in where.items()
    ]
    return " (" + ", ".join(parts) + ")"


def _render_lookup(spec: Mapping[str, Any], labels: Optional[Dict[str, str]] = None) -> str:
    table = str(spec["table"])
    _key, field, _unit = TABLES[table]
    text = (
        f"the {TABLE_LABELS[table]} {field} for this duration and attained age"
        + _render_where(spec.get("where"))
    )
    if spec.get("default") is not None:
        text += f" (or {_render_node(spec['default'], 0, labels)} if no row applies)"
    return text


def _render_rows_sum(spec: Mapping[str, Any], labels: Optional[Dict[str, str]] = None) -> str:
    table = str(spec["table"])
    text = (
        f"the sum over the {TABLE_LABELS[table]} rows in force of "
        f"({_render_node(spec['expr'], 0, labels)})"
        + _render_where(spec.get("where"))
    )
    if spec.get("exclude_where"):
        text += " excluding rows matching" + _render_where(spec["exclude_where"])
    return text


__all__ = [
    "COI_TIMINGS",
    "MECHANICS",
    "MECHANIC_LABELS",
    "MECHANIC_QUANTITIES",
    "ROW_QUANTITIES",
    "TABLES",
    "TABLE_LABELS",
    "TIMING_SENTENCES",
    "Unevaluable",
    "evaluate",
    "quantities_for",
    "render_equation",
    "render_with_timing",
    "select_row",
    "select_rows",
    "validate_equation",
]


# ---------------------------------------------------------------------------
# Canonical table-transcription bodies
#
# The standard readings of an accepted table, as equation bodies.  These
# are the bodies document transcription, migration, and the projection
# graph's no-run-context derivations use; each one states its table, its
# unit conversion, and its no-row default in the open.
# ---------------------------------------------------------------------------

def _lookup(table: str, *, default: Any = None, where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"table": table, "field": TABLES[table][1]}
    if where:
        spec["where"] = where
    if default is not None:
        spec["default"] = default
    return {"lookup": spec}


def coi_body_for_unit(unit: str) -> Dict[str, Any]:
    """The COI charge equation for a filed rate unit (monthly charge)."""

    rate = _lookup("coi")
    per_thousand = {"div": [{"qty": "nar"}, {"const": 1000}]}
    if unit == "per_1000_monthly":
        return {"mul": [per_thousand, rate]}
    if unit == "per_1000_annual":
        return {"div": [{"mul": [per_thousand, rate]}, {"const": 12}]}
    if unit == "percent_nar_annual":
        return {"div": [{"mul": [{"qty": "nar"}, rate]}, {"const": 12}]}
    raise ValueError(f"No equation transcription for COI rate unit {unit!r}")


def nar_body(definition: str) -> Dict[str, Any]:
    """The NAR equation for a stated definition."""

    if definition == "unadjusted":
        return {"max": [
            {"sub": [{"qty": "death_benefit"}, {"qty": "account_value"}]},
            {"const": 0},
        ]}
    if definition == "factor_adjusted":
        factor = _lookup("nar_factors", default={"const": 1})
        return {"max": [
            {"sub": [
                {"div": [{"qty": "death_benefit"}, factor]},
                {"qty": "account_value"},
            ]},
            {"const": 0},
        ]}
    raise ValueError(f"No equation transcription for NAR definition {definition!r}")


def death_benefit_body() -> Dict[str, Any]:
    """Death benefit = the greater of face and corridor % x account value."""

    corridor = _lookup("corridor", default={"const": 1})
    return {"max": [
        {"qty": "face_amount"},
        {"mul": [corridor, {"qty": "account_value"}]},
    ]}


def surrender_body_for_unit(unit: str) -> Dict[str, Any]:
    """The surrender charge equation for a filed charge unit.

    The lookup defaults to 0: a schedule that has ended charges nothing,
    and the rendering says so — the absence is stated by the equation,
    not improvised by the engine.
    """

    charge = _lookup("surrender", default={"const": 0})
    if unit == "percent_account_value":
        return {"mul": [charge, {"qty": "account_value"}]}
    if unit == "percent_face":
        return {"mul": [charge, {"qty": "face_amount"}]}
    if unit == "per_1000_face":
        return {"mul": [{"div": [{"qty": "face_amount"}, {"const": 1000}]}, charge]}
    if unit == "fixed":
        return charge
    raise ValueError(f"No equation transcription for surrender charge unit {unit!r}")


def premium_load_body() -> Dict[str, Any]:
    """Premium load = premium due x the load row's percentage of premium."""

    rate = _lookup("fees", where={"fee_unit": "percent_premium"}, default={"const": 0})
    return {"mul": [{"qty": "premium_due"}, rate]}


def policy_fees_body() -> Dict[str, Any]:
    """Monthly policy/admin fees = the sum over the fee schedule's rows.

    Each row converts on the basis its unit states — the conversion is
    written out in the equation (annual amounts / 12, per-$1,000
    amounts on the face, modal amounts only in payment months), never
    dispatched by hidden code.  Premium-load rows are excluded: they
    are taken from premiums by the premium_load equation.
    """

    per_row = {"if": {
        "cond": {"cmp": ["==", {"qty": "row_unit"}, {"str": "annual_fixed"}]},
        "then": {"div": [{"qty": "row_amount"}, {"const": 12}]},
        "else": {"if": {
            "cond": {"cmp": ["==", {"qty": "row_unit"}, {"str": "per_1000_face_annual"}]},
            "then": {"div": [
                {"mul": [{"div": [{"qty": "face_amount"}, {"const": 1000}]}, {"qty": "row_amount"}]},
                {"const": 12},
            ]},
            "else": {"if": {
                "cond": {"cmp": ["==", {"qty": "row_unit"}, {"str": "modal_fixed"}]},
                "then": {"mul": [{"qty": "row_amount"}, {"qty": "payment_due"}]},
                "else": {"qty": "row_amount"},
            }},
        }},
    }}
    return {"rows_sum": {
        "table": "fees",
        "exclude_where": {"fee_unit": "percent_premium"},
        "expr": per_row,
    }}


def crediting_body() -> Dict[str, Any]:
    """Interest credited = base x ((1 + guaranteed rate)^(1/12) - 1).

    The annual->monthly conversion is stated by the equation — it is
    exactly the kind of thing a filing can state differently, so it is
    never hidden in the skeleton.
    """

    return {"mul": [
        {"qty": "account_value"},
        {"sub": [
            {"pow": [{"add": [{"const": 1}, {"qty": "guaranteed_rate"}]}, {"div": [{"const": 1}, {"const": 12}]}]},
            {"const": 1},
        ]},
    ]}

