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
from eneo.database.tables.tenant_table import Tenants
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


def _flow_owned_json_columns() -> set[JsonbColumnKey]:
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

    keys.add((Tenants.__table__.name, Tenants.flow_settings.property.columns[0].name))
    return keys


def test_flow_jsonb_owner_registry_matches_sqlalchemy_metadata() -> None:
    discovered_columns = _flow_owned_json_columns()

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
        assert isinstance(owner.schema_version_policy, str)
        assert owner.schema_version_policy
        assert isinstance(owner.corruption_behavior, str)
        assert owner.corruption_behavior

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


def test_tenant_flow_settings_has_canonical_validated_owner() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("tenants", "flow_settings")]

    assert owner.owner_module == "eneo.flows.flow_settings"
    assert owner.envelope_name == "TenantFlowSettings"
    assert owner.owner_symbols == (
        "normalize_flow_settings_object",
        "validate_flow_settings_write",
        "validate_flow_settings_object",
    )
    assert owner.storage_category is FlowJsonbStorageCategory.AUTHORED_CONFIG
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE
    )
    assert owner.corruption_behavior is FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE


def test_resolved_input_edges_have_one_typed_immutable_owner() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[
        ("flow_step_attempt_resolved_inputs", "resolved_input_edges_jsonb")
    ]

    assert owner.owner_module == "eneo.flows.flow_run_provenance"
    assert owner.envelope_name == "FlowResolvedInputEdges"
    assert owner.owner_symbols == (
        "FlowResolvedInputEdges",
        "parse_resolved_input_edges",
    )
    assert owner.storage_category is FlowJsonbStorageCategory.PROVENANCE_EVIDENCE
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION
    )
    assert (
        owner.corruption_behavior
        is FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE
    )


def test_unexecuted_step_result_and_checkpoint_policies_are_plain_descriptions() -> (
    None
):
    step_result_keys = (
        ("flow_step_results", "input_payload_json"),
        ("flow_step_results", "output_payload_json"),
    )
    checkpoint_keys = (
        ("flow_run_review_checkpoints", "original_payload_json"),
        ("flow_run_review_checkpoints", "current_payload_json"),
        ("flow_run_review_checkpoints", "output_contract_json"),
        ("flow_run_review_checkpoints", "next_step_ids_json"),
    )

    for key in step_result_keys:
        owner = FLOW_JSONB_COLUMN_OWNERS[key]
        assert not isinstance(owner.schema_version_policy, FlowJsonbSchemaVersionPolicy)
        assert "no persisted schema version" in owner.schema_version_policy.lower()
        assert not isinstance(owner.corruption_behavior, FlowJsonbCorruptionBehavior)
        assert "no dedicated corruption" in owner.corruption_behavior.lower()

    for key in checkpoint_keys:
        owner = FLOW_JSONB_COLUMN_OWNERS[key]
        assert not isinstance(owner.schema_version_policy, FlowJsonbSchemaVersionPolicy)
        assert "written as 1 but is not read" in owner.schema_version_policy
        assert not isinstance(owner.corruption_behavior, FlowJsonbCorruptionBehavior)
        assert "no dedicated pre-write payload validation" in owner.corruption_behavior


def test_published_definition_has_verified_functional_and_forensic_owners() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("flow_versions", "definition_json")]

    assert owner.owner_module == "eneo.flows.published_definition"
    assert owner.envelope_name == "PublishedFlowDefinition"
    assert owner.owner_symbols == (
        "PublishedFlowDefinition",
        "build_published_definition_json",
        "parse_verified_published_definition",
        "inspect_published_definition_integrity",
    )
    assert owner.storage_category is FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT
    assert (
        owner.schema_version_policy is FlowJsonbSchemaVersionPolicy.CHECKSUMMED_SNAPSHOT
    )
    assert (
        owner.corruption_behavior is FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE
    )
    assert "Functional reads fail closed" in owner.rationale
    assert "authorized evidence" in owner.rationale


def test_builder_plan_proposal_json_has_typed_owner() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("builder_plans", "proposal_json")]

    assert owner.owner_module == "eneo.flows.ai_builder.ai_builder_domain_models"
    assert owner.envelope_name == "FlowBuilderProposal"
    assert owner.owner_symbols == (
        "FlowBuilderProposal",
        "FlowBuilderProposal.from_persisted_json",
        "FlowBuilderProposal.storage_json",
    )
    assert owner.storage_category is FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION
    )
    assert owner.corruption_behavior is FlowJsonbCorruptionBehavior.FAIL_PLAN_LOAD


def test_flow_package_import_plan_is_owner_validated_audit_shape() -> None:
    owner = FLOW_JSONB_COLUMN_OWNERS[("flow_package_imports", "import_plan_json")]

    assert owner.owner_module == "eneo.flow_packages.domain.flow_package_import_plan"
    assert owner.envelope_name == "FlowPackageImportPlan"
    assert owner.storage_category is FlowJsonbStorageCategory.IMPORT_STATE
    assert (
        owner.schema_version_policy
        is FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE
    )
    assert owner.corruption_behavior is FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE
    assert "auditable" in owner.rationale


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
