from __future__ import annotations

from importlib import import_module
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import JSON

from intric.database.tables import flow_tables
from intric.flows.infrastructure.flow_jsonb_ownership import (
    FLOW_JSONB_COLUMN_OWNERS,
    FlowJsonbCorruptionBehavior,
    FlowJsonbSchemaVersionPolicy,
    FlowJsonbStorageCategory,
    build_flow_jsonb_owner_map,
)

JsonbColumnKey = tuple[str, str]


def _flow_tables_json_columns() -> set[JsonbColumnKey]:
    import_module("intric.database.tables")

    keys: set[JsonbColumnKey] = set()
    for model in vars(flow_tables).values():
        if getattr(model, "__module__", None) != flow_tables.__name__:
            continue

        table = cast(sa.Table | None, getattr(model, "__table__", None))
        if table is None:
            continue

        for column in table.columns:
            if isinstance(column.type, (JSONB, JSON)):
                keys.add((table.name, column.name))

    return keys


def test_flow_jsonb_owner_registry_matches_sqlalchemy_metadata() -> None:
    discovered_columns = _flow_tables_json_columns()

    assert discovered_columns
    assert set(FLOW_JSONB_COLUMN_OWNERS) == discovered_columns


def test_flow_jsonb_owner_registry_entries_are_reviewable() -> None:
    for key, owner in FLOW_JSONB_COLUMN_OWNERS.items():
        assert owner.key == key
        assert owner.table_name == key[0]
        assert owner.column_name == key[1]
        assert owner.envelope_name
        assert owner.rationale
        assert "TODO" not in owner.rationale.upper()
        assert isinstance(owner.storage_category, FlowJsonbStorageCategory)
        assert isinstance(owner.schema_version_policy, FlowJsonbSchemaVersionPolicy)
        assert isinstance(owner.corruption_behavior, FlowJsonbCorruptionBehavior)

        import_module(owner.owner_module)


def test_flow_jsonb_owner_registry_rejects_duplicate_keys() -> None:
    owner = next(iter(FLOW_JSONB_COLUMN_OWNERS.values()))

    with pytest.raises(ValueError, match="Duplicate Flow JSONB ownership entry"):
        build_flow_jsonb_owner_map((owner, owner))


def test_flow_jsonb_owner_registry_has_explicit_deferred_inventory_rows() -> None:
    deferred_rows = {
        key
        for key, owner in FLOW_JSONB_COLUMN_OWNERS.items()
        if owner.storage_category is FlowJsonbStorageCategory.DEFERRED_INVENTORY
    }

    assert deferred_rows == {
        ("builder_plans", "edit_result_json"),
        ("builder_plans", "envelope_json"),
        ("builder_plans", "resource_bindings_json"),
        ("builder_plans", "spec_json"),
        ("builder_sessions", "conversation"),
        ("builder_sessions", "planning_state_jsonb"),
        ("module_registry", "metadata_json"),
    }
