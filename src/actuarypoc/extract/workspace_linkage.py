"""Equation <-> table linkage: which tables an equation reads, and
which equations read a table.

An equation is only half of a mechanic.  The approved formula bodies
the projection executes are full of table lookups — COI charge =
NAR / 1000 x *the COI table rate for this duration and attained age* —
and the tables they read are separate artifacts, accepted on their
own evidence.  Until now the two halves lived in different views:
the equations pane showed formulas, the mechanics panel showed
tables, and nothing stated which equation depended on which table.

This module derives that linkage exactly.  In the formula language
a table reference is a structural node — ``{"lookup": {"table": ...,
"field": ...}}`` or ``{"rows_sum": {"table": ...}}`` — so
dependencies are read off the body by walking the AST, never by
parsing the plain-language rendering or the filing's prose.  Each
dependency is then resolved against the workspace's tables in force
(the mechanics artifact's ``usable`` rows): a table that is present
resolves with its row count and provenance; a table that is absent
resolves to ``status: "missing"`` with the reason the product
already states for that absence (``table_not_extracted``) — never
dropped, never faked.

The reverse direction is derived the same way: a table's ``usedBy``
is the list of mechanics whose IN-FORCE equations look it up.  A
table no approved equation reads says so plainly (``unused``), and
mechanics whose merely-pending equations would read it are listed
separately (``usedByPending``) so a pending approval is never
mistaken for a live dependency.

Read-only: nothing in this module writes an artifact, a change
record, or a projection.  Approval semantics are untouched.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from actuarypoc.domain import equations as _eq
from actuarypoc.extract import workspace_equations as _ws_equations
from actuarypoc.extract.workspace_mechanics_panel import (
    STATUS_LABELS,
    _slot_status,
)


#: Every table a formula body can name, in product order.
TABLE_KEYS: "tuple[str, ...]" = tuple(_eq.TABLES)

#: Table name -> mechanics-panel slot id (nar_factors sits in "nar").
SLOT_ID_BY_TABLE: Dict[str, str] = {
    "coi": "coi",
    "surrender": "surrender",
    "fees": "fees",
    "nar_factors": "nar",
    "corridor": "corridor",
}

#: The reason the product already states when a filing's table has
#: not been extracted into the workspace (the structuring bridge's
#: blocked reason, Phase 8).  A dependency on an absent table
#: resolves with this class, verbatim.
MISSING_REASON = "table_not_extracted"

#: Change-log kinds that are events in a TABLE's history (acceptances,
#: replacements, corrections).  Equation approvals/rejections are
#: events in the equation's history and are deliberately excluded —
#: the equation card already carries that provenance.
_TABLE_CHANGE_KINDS = {
    "table_replace",
    "nar_factor",
    "proposal_accept",
    "correction",
    "correction_note",
}

#: Table-detail pagination: the default page and the hard cap.  The
#: live Promise UL COI table (242 rows) returns whole under the
#: default; the cap bounds any single response.
DETAIL_DEFAULT_LIMIT = 500
DETAIL_MAX_LIMIT = 1000

#: History entries returned by the table-detail payload.
_HISTORY_CAP = 50


# ---------------------------------------------------------------------------
# Derivation — dependencies read off the formula body, structurally.
# ---------------------------------------------------------------------------


def body_table_references(body: Any) -> List[Dict[str, Any]]:
    """The table references of one formula body, in first-seen order.

    Walks the AST for ``lookup`` and ``rows_sum`` nodes (including
    lookups nested inside a lookup's own default).  Each reference is
    deduplicated on (via, table, field, where, exclude_where,
    has-default): the same lookup written twice is one dependency.
    References to tables the language does not know cannot occur in a
    validated body; if one appears anyway it is skipped, not guessed.
    """

    references: List[Dict[str, Any]] = []
    seen = set()

    def add(via: str, spec: Any) -> None:
        if not isinstance(spec, dict):
            return
        table = spec.get("table")
        if table not in _eq.TABLES:
            return
        table = str(table)
        field = str(spec.get("field") or _eq.TABLES[table][1])
        where = spec.get("where") if isinstance(spec.get("where"), dict) else None
        exclude = (
            spec.get("exclude_where")
            if isinstance(spec.get("exclude_where"), dict) else None
        )
        has_default = spec.get("default") is not None
        key = (
            via, table, field,
            json.dumps(where, sort_keys=True, default=str),
            json.dumps(exclude, sort_keys=True, default=str),
            has_default,
        )
        if key in seen:
            return
        seen.add(key)
        references.append({
            "table": table,
            "field": field,
            "via": via,
            "where": deepcopy(where),
            "excludeWhere": deepcopy(exclude),
            "hasDefault": has_default,
        })

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            keys = set(node.keys())
            if keys == {"lookup"}:
                add("lookup", node.get("lookup"))
            elif keys == {"rows_sum"}:
                add("rows_sum", node.get("rows_sum"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    return references


# ---------------------------------------------------------------------------
# Resolution — a table in force, as the linkage payload states it.
# ---------------------------------------------------------------------------


def _source_views(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Distinct provenance views over a table's rows (acceptance incl.)."""

    seen: List[Dict[str, Any]] = []
    for row in rows:
        provenance = row.get("provenance") or {}
        view = {
            "filename": provenance.get("filename"),
            "page": provenance.get("page"),
            "tableHeading": provenance.get("tableHeading"),
            "valueBasis": provenance.get("valueBasis"),
            "sourceType": provenance.get("sourceType"),
            "reviewStatus": provenance.get("reviewStatus"),
            "reviewedBy": provenance.get("reviewedBy"),
            "reviewedAt": provenance.get("reviewedAt"),
        }
        if any(value is not None for value in view.values()) and view not in seen:
            seen.append(view)
    return seen


def table_view(artifact: Mapping[str, Any], table: str) -> Dict[str, Any]:
    """One table's in-force state, resolved from the artifact alone.

    ``status`` is the linkage contract's word: ``filed`` when rows
    are in force, ``missing`` when none are.  ``basis`` carries the
    mechanics panel's finer derivation (filed_accepted,
    workspace_table, synthetic, corrected, ...) so the display can
    stay honest about WHERE the rows came from.  Acceptance (by/at)
    is the filed acceptance stamped on the rows' provenance, falling
    back to the workspace-edit stamp for an edited table.
    """

    artifact = artifact or {}
    key = _eq.TABLES[table][0]
    rows = list(((artifact.get("usable") or {}).get(key)) or [])
    sources = _source_views(rows)
    first = sources[0] if sources else {}

    accepted_by: Optional[str] = None
    accepted_at: Optional[str] = None
    for source in sources:
        if source.get("reviewedBy") or source.get("reviewedAt"):
            accepted_by = source.get("reviewedBy")
            accepted_at = source.get("reviewedAt")
            break
    if accepted_by is None and accepted_at is None:
        edit = ((artifact.get("workspaceEdits") or {}).get(key)) or {}
        if edit:
            accepted_by = edit.get("updatedBy")
            accepted_at = edit.get("updatedAt")

    basis = _slot_status(dict(artifact), key)
    return {
        "table": table,
        "label": _eq.TABLE_LABELS[table],
        "status": "filed" if rows else "missing",
        "basis": basis,
        "statusLabel": STATUS_LABELS.get(basis, basis),
        "rowCount": len(rows),
        "sources": sources,
        "sourceFilename": first.get("filename"),
        "sourcePage": first.get("page"),
        "tableSourceType": first.get("sourceType"),
        "acceptedBy": accepted_by,
        "acceptedAt": accepted_at,
    }


def _missing_note(table: str, has_default: bool) -> str:
    label = _eq.TABLE_LABELS[table]
    if has_default:
        return (
            f"This equation reads the {label}, but no {label} has been "
            f"extracted into this workspace yet ({MISSING_REASON}). Until "
            "a table is in force the equation uses the fallback its own "
            "statement names."
        )
    return (
        f"This equation reads the {label}, but no {label} has been "
        f"extracted into this workspace yet ({MISSING_REASON}). Until "
        "a table is in force this equation cannot be evaluated where "
        "a row is needed."
    )


def resolve_dependencies(
    body: Any, views_by_table: Mapping[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """A body's table references, each resolved against tables in force."""

    resolved: List[Dict[str, Any]] = []
    for reference in body_table_references(body):
        view = views_by_table[reference["table"]]
        dependency = {
            **reference,
            "label": view["label"],
            "status": view["status"],
            "basis": view["basis"],
            "rowCount": view["rowCount"],
            "sourceFilename": view["sourceFilename"],
            "sourcePage": view["sourcePage"],
            "acceptedBy": view["acceptedBy"],
            "acceptedAt": view["acceptedAt"],
        }
        if view["status"] == "missing":
            dependency["missingReason"] = MISSING_REASON
            dependency["note"] = _missing_note(
                reference["table"], reference["hasDefault"]
            )
        resolved.append(dependency)
    return resolved


def tables_linkage(artifact: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every table's view, with its reverse linkage (``usedBy``).

    ``usedBy`` names the mechanics whose IN-FORCE (approved) equations
    look the table up — the live dependencies a table swap would
    move.  ``usedByPending`` names mechanics with a pending equation
    that would read it; it is reported separately and never merged
    into ``usedBy``.  ``unused`` is true when no approved equation
    reads the table at all.
    """

    artifact = artifact or {}
    views = {table: table_view(artifact, table) for table in TABLE_KEYS}

    used_by: Dict[str, List[str]] = {table: [] for table in TABLE_KEYS}
    for mechanic in _eq.MECHANICS:
        record = _ws_equations.in_force(artifact, mechanic)
        if record is None or record.get("body") is None:
            continue
        for reference in body_table_references(record["body"]):
            if mechanic not in used_by[reference["table"]]:
                used_by[reference["table"]].append(mechanic)

    used_by_pending: Dict[str, List[str]] = {table: [] for table in TABLE_KEYS}
    for record in _ws_equations.records(artifact):
        if record.get("state") != "pending" or record.get("body") is None:
            continue
        mechanic = str(record.get("mechanic") or "")
        if mechanic not in _eq.MECHANICS:
            continue
        for reference in body_table_references(record["body"]):
            if mechanic not in used_by_pending[reference["table"]]:
                used_by_pending[reference["table"]].append(mechanic)

    tables: List[Dict[str, Any]] = []
    for table in TABLE_KEYS:
        view = dict(views[table])
        view["usedBy"] = used_by[table]
        view["usedByPending"] = used_by_pending[table]
        view["unused"] = not used_by[table]
        tables.append(view)
    return tables


def enrich_equations_view(
    view: Dict[str, Any], artifact: Mapping[str, Any]
) -> Dict[str, Any]:
    """Attach table linkage to an ``equations_view`` payload, in place.

    Every record with a body — the in-force equation and each pending
    one alike — gains ``tableDependencies``; the payload gains a
    top-level ``tables`` list carrying each table's reverse linkage.
    Records without a body (stated-but-unmapped) gain an empty list:
    they propose no readable formula, so they depend on nothing yet.
    """

    artifact = artifact or {}
    views_by_table = {table: table_view(artifact, table) for table in TABLE_KEYS}
    dependencies_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for record in _ws_equations.records(artifact):
        if record.get("body") is not None:
            dependencies_by_id[str(record.get("id"))] = resolve_dependencies(
                record["body"], views_by_table
            )

    for mechanic_view in (view.get("mechanics") or {}).values():
        if not isinstance(mechanic_view, dict):
            continue
        for record in mechanic_view.get("records") or []:
            record["tableDependencies"] = dependencies_by_id.get(
                str(record.get("id")), []
            )
        in_force = mechanic_view.get("inForce")
        if isinstance(in_force, dict):
            in_force["tableDependencies"] = dependencies_by_id.get(
                str(in_force.get("id")), []
            )
    view["tables"] = tables_linkage(artifact)
    return view


# ---------------------------------------------------------------------------
# Table detail — the rows themselves, their provenance, their history.
# ---------------------------------------------------------------------------


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _table_history(
    artifact: Mapping[str, Any],
    table: str,
    changes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """The table's acceptance / swap history, as the store records it.

    Assembled from three recorded sources, never invented:

    * the persisted change log, filtered to this table's slot and to
      change kinds that are table events (acceptances through the
      proposal flow, in-workspace replacements, corrections);
    * the filed acceptance stamped on the in-force rows' own
      provenance (reviewedBy / reviewedAt) — the manual review path
      records acceptance there and writes no change entry, so
      without this the commonest acceptance would be invisible;
    * the workspace-edit stamp, when an edit replaced the table and
      no change entry already records that same edit.

    A provenance acceptance and a change entry describing the same
    event (same person, timestamps within two minutes — the two
    clocks are stamped moments apart by different code paths) are
    merged: the change entry, with its fuller summary, wins.
    """

    artifact = artifact or {}
    key = _eq.TABLES[table][0]
    entries: List[Dict[str, Any]] = []

    for change in changes or []:
        if not isinstance(change, dict):
            continue
        if change.get("kind") not in _TABLE_CHANGE_KINDS:
            continue
        # Every table-event change record carries the table key in
        # its ``mechanic`` field (the mechanics panel's change
        # factory); equation events carry an equation mechanic and
        # are excluded by kind above besides.
        if change.get("mechanic") != key:
            continue
        entries.append({
            "kind": change.get("kind"),
            "who": change.get("who"),
            "at": change.get("at"),
            "summary": change.get("summary"),
            "prior": change.get("prior"),
            "new": change.get("new"),
            "recordedAs": "change_log",
        })

    covered = [
        (entry.get("who"), _parse_timestamp(entry.get("at"))) for entry in entries
    ]

    def already_recorded(who: Any, at: Any, kinds: Optional[set] = None) -> bool:
        stamp = _parse_timestamp(at)
        for entry_who, entry_stamp in covered:
            if entry_who != who:
                continue
            if stamp is None or entry_stamp is None:
                if at == entry_stamp:
                    return True
                continue
            if abs((stamp - entry_stamp).total_seconds()) <= 120:
                return True
        return False

    rows = list(((artifact.get("usable") or {}).get(key)) or [])
    for source in _source_views(rows):
        if not (source.get("reviewedBy") or source.get("reviewedAt")):
            continue
        if already_recorded(source.get("reviewedBy"), source.get("reviewedAt")):
            continue
        row_count = sum(
            1 for row in rows
            if (row.get("provenance") or {}).get("filename") == source.get("filename")
            and (row.get("provenance") or {}).get("reviewedAt") == source.get("reviewedAt")
        )
        origin = str(source.get("filename") or "the filing")
        if source.get("page") is not None:
            origin += f", p. {source['page']}"
        entries.append({
            "kind": "filed_acceptance",
            "who": source.get("reviewedBy"),
            "at": source.get("reviewedAt"),
            "summary": (
                f"Filed {_eq.TABLE_LABELS[table]} accepted — {row_count} "
                f"row{'s' if row_count != 1 else ''} from {origin}."
            ),
            "prior": None,
            "new": {"rowCount": row_count, "status": "filed_accepted"},
            "recordedAs": "row_provenance",
        })
        covered.append((source.get("reviewedBy"), _parse_timestamp(source.get("reviewedAt"))))

    edit = ((artifact.get("workspaceEdits") or {}).get(key)) or {}
    if edit and not already_recorded(edit.get("updatedBy"), edit.get("updatedAt")):
        entries.append({
            "kind": "workspace_edit",
            "who": edit.get("updatedBy"),
            "at": edit.get("updatedAt"),
            "summary": (
                f"{_eq.TABLE_LABELS[table].capitalize()} replaced by a "
                "workspace edit."
            ),
            "prior": None,
            "new": {"rowCount": len(edit.get("rows") or [])},
            "recordedAs": "workspace_edit",
        })

    entries.sort(
        key=lambda entry: _parse_timestamp(entry.get("at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return entries[:_HISTORY_CAP]


def table_detail(
    artifact: Mapping[str, Any],
    table: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    offset: int = 0,
    limit: int = DETAIL_DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """One table in full: rows (paged), provenance, history, used-by.

    Rows are the workspace's accepted rows exactly as stored,
    provenance included.  ``limit`` is clamped to DETAIL_MAX_LIMIT;
    the live 242-row COI table returns whole under the default page.
    """

    artifact = artifact or {}
    key = _eq.TABLES[table][0]
    rows = list(((artifact.get("usable") or {}).get(key)) or [])
    limit = max(1, min(int(limit), DETAIL_MAX_LIMIT))
    offset = max(0, int(offset))
    page = rows[offset:offset + limit]

    linkage = next(
        entry for entry in tables_linkage(artifact) if entry["table"] == table
    )
    detail = dict(linkage)
    detail.update({
        "rows": deepcopy(page),
        "rowsReturned": len(page),
        "offset": offset,
        "limit": limit,
        # True when this page is not the whole table — rows remain
        # beyond it, or an offset skipped rows before it.
        "truncated": offset > 0 or offset + len(page) < len(rows),
        "history": _table_history(artifact, table, changes),
    })
    return detail


__all__ = [
    "TABLE_KEYS",
    "SLOT_ID_BY_TABLE",
    "MISSING_REASON",
    "DETAIL_DEFAULT_LIMIT",
    "DETAIL_MAX_LIMIT",
    "body_table_references",
    "table_view",
    "resolve_dependencies",
    "tables_linkage",
    "enrich_equations_view",
    "table_detail",
]
