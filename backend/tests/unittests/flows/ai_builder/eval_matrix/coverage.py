"""Coverage-policy computation over the buildable golden set.

Every count and ratio here is over `BuildableGoldenCase` only: gap and planned
rows are not buildable behaviour and must neither dilute nor inflate coverage.
Row-level complexity requirements come from the `RowComplexityPolicy` in
`taxonomy.py`; the other composition columns are governed by the global
per-column threshold the test layer applies.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .derivation import derive_composition_columns
from .golden_cases import GOLDEN_CASES, BuildableGoldenCase
from .taxonomy import (
    CapabilityRow,
    CompositionColumn,
    CoverageRequirement,
    MatrixRowState,
    expected_state,
    row_complexity_policy,
)

_HTTP_ROWS: tuple[CapabilityRow, ...] = (
    CapabilityRow.HTTP_POST_CALL,
    CapabilityRow.HTTP_GET_CALL,
)

_COMPLEXITY_COLUMNS: tuple[CompositionColumn, ...] = (
    CompositionColumn.BASIC_SINGLE_STEP,
    CompositionColumn.ADVANCED_MULTI_CAPABILITY,
)

# How many goldens an HTTP row must carry once the AI Builder can author it.
_HTTP_REQUIRED_GOLDENS = 2


def _columns_by_row(
    goldens: Sequence[BuildableGoldenCase],
) -> dict[CapabilityRow, set[CompositionColumn]]:
    covered: dict[CapabilityRow, set[CompositionColumn]] = {}
    for case in goldens:
        covered.setdefault(case.capability_row, set()).update(
            derive_composition_columns(case)
        )
    return covered


def unsatisfied_required_columns(
    goldens: Sequence[BuildableGoldenCase] = GOLDEN_CASES,
) -> dict[CapabilityRow, list[CompositionColumn]]:
    """Rows whose policy REQUIRES a complexity column no golden derives."""
    covered = _columns_by_row(goldens)
    result: dict[CapabilityRow, list[CompositionColumn]] = {}
    for row in CapabilityRow:
        policy = row_complexity_policy(row)
        if policy is None:
            continue
        missing = [
            column
            for column in _COMPLEXITY_COLUMNS
            if policy.requirement_for(column) is CoverageRequirement.REQUIRED
            and column not in covered.get(row, set())
        ]
        if missing:
            result[row] = missing
    return result


def not_applicable_violations(
    goldens: Sequence[BuildableGoldenCase] = GOLDEN_CASES,
) -> list[tuple[str, CompositionColumn]]:
    """Goldens that derive a complexity column their row marks NOT_APPLICABLE."""
    violations: list[tuple[str, CompositionColumn]] = []
    for case in goldens:
        policy = row_complexity_policy(case.capability_row)
        if policy is None:
            continue
        derived = derive_composition_columns(case)
        for column in _COMPLEXITY_COLUMNS:
            if (
                policy.requirement_for(column) is CoverageRequirement.NOT_APPLICABLE
                and column in derived
            ):
                violations.append((case.case_id, column))
    return violations


def distinct_rows_per_column(
    goldens: Sequence[BuildableGoldenCase] = GOLDEN_CASES,
) -> dict[CompositionColumn, int]:
    """How many distinct capability rows cover each composition column."""
    rows_by_column: dict[CompositionColumn, set[CapabilityRow]] = {}
    for case in goldens:
        for column in derive_composition_columns(case):
            rows_by_column.setdefault(column, set()).add(case.capability_row)
    return {column: len(rows) for column, rows in rows_by_column.items()}


def composition_ratio(
    column: CompositionColumn,
    goldens: Sequence[BuildableGoldenCase] = GOLDEN_CASES,
) -> float:
    """Fraction of buildable goldens whose shape derives `column`."""
    if not goldens:
        return 0.0
    matching = sum(1 for case in goldens if column in derive_composition_columns(case))
    return matching / len(goldens)


def http_required_goldens(state: MatrixRowState) -> int:
    """Goldens an HTTP row must carry: deferred to 0 while the row is a gap,
    reactivating to the real requirement once the row is promoted to buildable.

    This keeps the contract's "HTTP POST/GET each >= 2 goldens" alive as a
    deferred obligation instead of silently dropping it: the moment HTTP becomes
    authorable and the row flips to buildable, the requirement returns.
    """
    return _HTTP_REQUIRED_GOLDENS if state == "buildable" else 0


def http_threshold_violations(
    goldens: Sequence[BuildableGoldenCase] = GOLDEN_CASES,
    *,
    state_of: Callable[[CapabilityRow], MatrixRowState] = expected_state,
) -> list[CapabilityRow]:
    """HTTP rows that are buildable but carry fewer than the required goldens.

    Empty while HTTP stays a gap (the requirement is deferred to zero). The
    `state_of` seam lets tests exercise the reactivated-buildable case without
    mutating the real matrix state.
    """
    counts: dict[CapabilityRow, int] = {}
    for case in goldens:
        counts[case.capability_row] = counts.get(case.capability_row, 0) + 1
    return [
        row
        for row in _HTTP_ROWS
        if counts.get(row, 0) < http_required_goldens(state_of(row))
    ]
