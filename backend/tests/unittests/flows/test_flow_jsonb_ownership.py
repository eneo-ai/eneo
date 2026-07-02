from __future__ import annotations

import inspect
from importlib import import_module
from types import ModuleType
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import JSON

from eneo.database.tables import flow_tables
from eneo.flows.infrastructure.flow_jsonb_ownership import (
    FLOW_JSONB_COLUMN_OWNERS,
    FlowJsonbCorruptionBehavior,
    FlowJsonbSchemaVersionPolicy,
    FlowJsonbStorageCategory,
    build_flow_jsonb_owner_map,
)

JsonbColumnKey = tuple[str, str]


def _resolve_owner_symbol(module: ModuleType, symbol_path: str) -> object:
    resolved: object = module
    for symbol_part in symbol_path.split("."):
        resolved = getattr(resolved, symbol_part)
    return resolved


def _is_executable_owner_symbol(symbol: object) -> bool:
    return inspect.isclass(symbol) or inspect.isfunction(symbol) or callable(symbol)


def _flow_tables_json_columns() -> set[JsonbColumnKey]:
    import_module("eneo.database.tables")

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

        module = import_module(owner.owner_module)
        assert owner.owner_symbols, f"{owner.table_name}.{owner.column_name}"
        for symbol_path in owner.owner_symbols:
            assert not symbol_path.endswith(("Service", "Repository"))
            symbol = _resolve_owner_symbol(module, symbol_path)
            assert _is_executable_owner_symbol(symbol), (
                f"{owner.table_name}.{owner.column_name} owner symbol "
                f"{owner.owner_module}.{symbol_path} is not executable"
            )


def test_flow_jsonb_owner_registry_rejects_duplicate_keys() -> None:
    owner = next(iter(FLOW_JSONB_COLUMN_OWNERS.values()))

    with pytest.raises(ValueError, match="Duplicate Flow JSONB ownership entry"):
        build_flow_jsonb_owner_map((owner, owner))


def test_flow_jsonb_owner_registry_has_no_deferred_inventory_escape_hatch() -> None:
    for enum_type in (
        FlowJsonbStorageCategory,
        FlowJsonbSchemaVersionPolicy,
        FlowJsonbCorruptionBehavior,
    ):
        assert "deferred_inventory" not in {item.value for item in enum_type}


def test_builder_plan_proposal_json_has_typed_owner() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("builder_plans", "proposal_json")]

    assert owner.owner_module == "eneo.flows.ai_builder.ai_builder_domain_models"
    assert owner.envelope_name == "FlowBuilderProposal"
    assert owner.storage_category is FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE
    )
    assert owner.corruption_behavior is FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE


def test_builder_session_conversation_has_typed_owner() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("builder_sessions", "conversation")]

    assert owner.owner_module == "eneo.flows.ai_builder.ai_builder_domain_models"
    assert owner.envelope_name == "ConversationMessage"
    assert owner.storage_category is FlowJsonbStorageCategory.BUILDER_SESSION_STATE
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE
    )
    assert owner.corruption_behavior is FlowJsonbCorruptionBehavior.FAIL_SESSION_LOAD


def test_builder_session_planning_state_has_typed_owner() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("builder_sessions", "planning_state_jsonb")]

    assert owner.owner_module == "eneo.flows.ai_builder.planning_state"
    assert owner.envelope_name == "PlanningState"
    assert owner.storage_category is FlowJsonbStorageCategory.BUILDER_SESSION_STATE
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION
    )
    assert owner.corruption_behavior is FlowJsonbCorruptionBehavior.FAIL_SESSION_LOAD
