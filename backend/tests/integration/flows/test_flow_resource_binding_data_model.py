from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.flow_tables import (
    FLOW_RESOURCE_BINDING_SOURCE_VALUES,
    FLOW_RESOURCE_LOCAL_RESOURCE_KIND_VALUES,
    FLOW_RESOURCE_SLOT_KIND_VALUES,
    FLOW_RESOURCE_SLOT_LOCAL_KIND_PAIR_VALUES,
    FlowResourceBindings,
    Flows,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.flow_resource_bindings import (
    RESOURCE_SLOT_LOCAL_KIND_PAIRS,
    RESOURCE_SLOT_PATTERN,
    UUID_SHAPED_RESOURCE_REF_PATTERN,
    FlowResourceBindingSource,
    LocalResourceKind,
    ResourceSlotKind,
)


def _constraint_names(table: object) -> set[str]:
    return {
        constraint.name or ""
        for constraint in table.__table__.constraints
        if constraint.name is not None
    }


def _unique_columns(table: object, constraint_name: str) -> tuple[str, ...]:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.name == constraint_name
        ):
            return tuple(column.name for column in constraint.columns)
    raise AssertionError(f"Unique constraint {constraint_name} was not found.")


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def _check_constraint_values(table: object, constraint_name: str) -> tuple[str, ...]:
    return tuple(
        re.findall(r"'([^']+)'", _check_constraint_sql(table, constraint_name))
    )


def _check_constraint_pairs(
    table: object,
    constraint_name: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        re.findall(
            r"\('([^']+)','([^']+)'\)",
            _check_constraint_sql(table, constraint_name),
        )
    )


def _index_by_name(table: object, index_name: str) -> Index:
    for index in table.__table__.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"Index {index_name} was not found.")


async def _create_flow(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
) -> Flows:
    model = await completion_model_factory(
        session,
        f"flow-resource-binding-model-{uuid4()}",
    )
    space = await space_factory(
        session,
        f"Flow resource bindings {uuid4()}",
        [model.id],
    )
    flow = Flows(
        name=f"Flow resource bindings {uuid4()}",
        description=None,
        tenant_id=admin_user.tenant_id,
        space_id=space.id,
        created_by_user_id=admin_user.id,
        owner_user_id=admin_user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
    )
    session.add(flow)
    await session.flush()
    return flow


def _binding(
    *,
    flow: Flows,
    slot_kind: str = ResourceSlotKind.MODEL.value,
    slot: str = "structured-extraction",
    slot_label: str = "Structured extraction",
    local_resource_kind: str = LocalResourceKind.COMPLETION_MODEL.value,
    local_resource_id: UUID | None = None,
    tenant_id: UUID | None = None,
    source: str = "ai_builder",
) -> FlowResourceBindings:
    return FlowResourceBindings(
        flow_id=flow.id,
        tenant_id=tenant_id or flow.tenant_id,
        space_id=flow.space_id,
        slot_kind=slot_kind,
        slot=slot,
        slot_label=slot_label,
        local_resource_kind=local_resource_kind,
        local_resource_id=local_resource_id or uuid4(),
        source=source,
    )


async def _assert_integrity_error(session, row: FlowResourceBindings) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(row)
            await session.flush()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_round_trips(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        local_resource_id = uuid4()
        row = _binding(
            flow=flow,
            slot_kind=ResourceSlotKind.KNOWLEDGE.value,
            slot="local-policy",
            slot_label="Local policy",
            local_resource_kind=LocalResourceKind.COLLECTION.value,
            local_resource_id=local_resource_id,
            source="package_import",
        )

        session.add(row)
        await session.flush()

        fetched = await session.scalar(
            sa.select(FlowResourceBindings).where(FlowResourceBindings.id == row.id)
        )

        assert fetched is not None
        assert fetched.flow_id == flow.id
        assert fetched.tenant_id == flow.tenant_id
        assert fetched.space_id == flow.space_id
        assert fetched.slot_kind == ResourceSlotKind.KNOWLEDGE.value
        assert fetched.slot == "local-policy"
        assert fetched.slot_label == "Local policy"
        assert fetched.local_resource_kind == LocalResourceKind.COLLECTION.value
        assert fetched.local_resource_id == local_resource_id
        assert fetched.source == "package_import"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_rejects_duplicate_slot_for_flow(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        session.add(_binding(flow=flow))
        await session.flush()

        await _assert_integrity_error(session, _binding(flow=flow))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_accepts_multiple_slots_for_same_local_target(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        local_resource_id = uuid4()
        session.add(
            _binding(
                flow=flow,
                slot="source-model-a",
                slot_label="Source model A",
                local_resource_id=local_resource_id,
            )
        )
        session.add(
            _binding(
                flow=flow,
                slot="source-model-b",
                slot_label="Source model B",
                local_resource_id=local_resource_id,
            )
        )

        await session.flush()

        rows = (
            (
                await session.execute(
                    sa.select(FlowResourceBindings)
                    .where(FlowResourceBindings.flow_id == flow.id)
                    .order_by(FlowResourceBindings.slot.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [row.slot for row in rows] == ["source-model-a", "source-model-b"]
        assert {row.local_resource_id for row in rows} == {local_resource_id}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slot_kind", "unknown"),
        ("slot", "550e8400-e29b-41d4-a716-446655440000"),
        ("slot", "abcdef12-abcd-4abc-8def-abcdef012345"),
        ("slot_label", " "),
        ("local_resource_kind", "unknown"),
        ("source", "unknown"),
    ],
)
async def test_flow_resource_binding_rejects_invalid_contract_values(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
    field: str,
    value: str,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        values = {field: value}

        await _assert_integrity_error(session, _binding(flow=flow, **values))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_accepts_all_declared_slot_local_kind_pairs(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        for index, (
            slot_kind,
            local_resource_kind,
        ) in enumerate(RESOURCE_SLOT_LOCAL_KIND_PAIRS):
            session.add(
                _binding(
                    flow=flow,
                    slot_kind=slot_kind,
                    slot=f"resource-binding-pair-{index}",
                    local_resource_kind=local_resource_kind,
                )
            )

        await session.flush()

        row_count = await session.scalar(
            sa.select(sa.func.count(FlowResourceBindings.id)).where(
                FlowResourceBindings.flow_id == flow.id
            )
        )
        assert row_count == len(RESOURCE_SLOT_LOCAL_KIND_PAIRS)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_rejects_invalid_slot_local_kind_pair(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )

        await _assert_integrity_error(
            session,
            _binding(
                flow=flow,
                slot_kind=ResourceSlotKind.MODEL.value,
                local_resource_kind=LocalResourceKind.MCP_TOOL.value,
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_rejects_cross_tenant_flow_reference(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        other_tenant = Tenants(
            name=f"flow_resource_binding_tenant_{uuid4()}",
            display_name=None,
            slug=f"flow-resource-binding-{uuid4()}",
            quota_limit=1024**3,
        )
        session.add(other_tenant)
        await session.flush()

        await _assert_integrity_error(
            session,
            _binding(flow=flow, tenant_id=other_tenant.id),
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_resource_binding_soft_delete_and_hard_delete_semantics(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        flow = await _create_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        row = _binding(flow=flow)
        session.add(row)
        await session.flush()

        flow.deleted_at = datetime.now(timezone.utc)
        await session.flush()
        assert (
            await session.scalar(
                sa.select(sa.func.count(FlowResourceBindings.id)).where(
                    FlowResourceBindings.flow_id == flow.id
                )
            )
            == 1
        )

        await session.delete(flow)
        await session.flush()
        assert (
            await session.scalar(
                sa.select(sa.func.count(FlowResourceBindings.id)).where(
                    FlowResourceBindings.flow_id == flow.id
                )
            )
            == 0
        )


def test_flow_resource_binding_metadata_matches_resource_ref_contract() -> None:
    assert FLOW_RESOURCE_SLOT_KIND_VALUES == tuple(
        item.value for item in ResourceSlotKind
    )
    assert FLOW_RESOURCE_LOCAL_RESOURCE_KIND_VALUES == tuple(
        item.value for item in LocalResourceKind
    )
    assert FLOW_RESOURCE_SLOT_LOCAL_KIND_PAIR_VALUES == RESOURCE_SLOT_LOCAL_KIND_PAIRS
    assert FLOW_RESOURCE_BINDING_SOURCE_VALUES == (
        FlowResourceBindingSource.AI_BUILDER.value,
        FlowResourceBindingSource.PACKAGE_IMPORT.value,
        FlowResourceBindingSource.MANUAL_ADMIN.value,
    )
    assert (
        _check_constraint_values(
            FlowResourceBindings,
            "ck_flow_resource_bindings_slot_kind",
        )
        == FLOW_RESOURCE_SLOT_KIND_VALUES
    )
    assert (
        _check_constraint_values(
            FlowResourceBindings,
            "ck_flow_resource_bindings_local_resource_kind",
        )
        == FLOW_RESOURCE_LOCAL_RESOURCE_KIND_VALUES
    )
    assert (
        _check_constraint_pairs(
            FlowResourceBindings,
            "ck_flow_resource_bindings_slot_local_kind_pair",
        )
        == FLOW_RESOURCE_SLOT_LOCAL_KIND_PAIR_VALUES
    )
    assert (
        _check_constraint_values(
            FlowResourceBindings,
            "ck_flow_resource_bindings_source",
        )
        == FLOW_RESOURCE_BINDING_SOURCE_VALUES
    )
    assert "ck_flow_resource_bindings_slot_format" in _constraint_names(
        FlowResourceBindings
    )
    assert "ck_flow_resource_bindings_slot_not_uuid" in _constraint_names(
        FlowResourceBindings
    )
    assert "ck_flow_resource_bindings_slot_label_not_empty" in _constraint_names(
        FlowResourceBindings
    )
    assert RESOURCE_SLOT_PATTERN in _check_constraint_sql(
        FlowResourceBindings,
        "ck_flow_resource_bindings_slot_format",
    )
    assert UUID_SHAPED_RESOURCE_REF_PATTERN in _check_constraint_sql(
        FlowResourceBindings,
        "ck_flow_resource_bindings_slot_not_uuid",
    )
    assert _unique_columns(
        FlowResourceBindings,
        "uq_flow_resource_bindings_flow_slot",
    ) == ("flow_id", "slot_kind", "slot")

    local_target_index = _index_by_name(
        FlowResourceBindings,
        "ix_flow_resource_bindings_local_target",
    )
    assert tuple(column.name for column in local_target_index.columns) == (
        "local_resource_kind",
        "local_resource_id",
    )
