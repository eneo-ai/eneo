"""The run deletion's child tables follow the foreign-key graph below flow_runs."""

from __future__ import annotations

import eneo.database.tables  # noqa: F401
from eneo.database.tables.flow_tables import FlowRuns
from eneo.flows.infrastructure.flow_run_deletion_repo import FLOW_RUN_CHILD_TABLES


def _referencing(parent: str) -> set[str]:
    return {
        table.name
        for table in FlowRuns.metadata.tables.values()
        for constraint in table.foreign_key_constraints
        if constraint.referred_table.name == parent
    }


def test_every_table_below_flow_runs_is_deleted_and_none_twice() -> None:
    """Mutant M140 omitted_child lets the root cascade bypass the row cap."""
    below: set[str] = set()
    frontier = {FlowRuns.__tablename__}
    while frontier:
        parent = frontier.pop()
        for child in _referencing(parent) - below:
            below.add(child)
            frontier.add(child)
    ordered = [table.__tablename__ for table, _ in FLOW_RUN_CHILD_TABLES]

    assert len(ordered) == len(set(ordered))
    assert set(ordered) == below


def test_a_table_is_deleted_before_every_table_it_references() -> None:
    """Mutant M141 child_after_parent violates the actual foreign-key order."""
    position = {
        table.__tablename__: index
        for index, (table, _) in enumerate(FLOW_RUN_CHILD_TABLES)
    }
    for table, _ in FLOW_RUN_CHILD_TABLES:
        for constraint in table.__table__.foreign_key_constraints:
            parent = constraint.referred_table.name
            if parent in position and parent != table.__tablename__:
                assert position[table.__tablename__] < position[parent], (
                    table.__tablename__,
                    parent,
                )
