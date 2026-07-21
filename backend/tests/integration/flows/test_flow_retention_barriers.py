from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import product
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
    FlowRetentionOrganizationProposal,
)
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.database.tables.flow_tables import FlowRuns, Flows, FlowVersions
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.infrastructure.flow_repo import FlowRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg13",
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    )
    with postgres:
        postgres.get_connection_url()
        yield postgres


@dataclass(frozen=True, slots=True)
class _BarrierCase:
    organization_minimum_days: int | None
    classification_minimum_days: int | None
    organization_no_purge: bool
    classification_no_purge: bool

    @property
    def label(self) -> str:
        return (
            f"org-min-{self.organization_minimum_days}-"
            f"class-min-{self.classification_minimum_days}-"
            f"org-no-purge-{self.organization_no_purge}-"
            f"class-no-purge-{self.classification_no_purge}"
        )

    @property
    def effective_minimum_days(self) -> int | None:
        configured = tuple(
            days
            for days in (
                self.organization_minimum_days,
                self.classification_minimum_days,
            )
            if days is not None
        )
        return max(configured) if configured else None

    @property
    def no_purge(self) -> bool:
        return self.organization_no_purge or self.classification_no_purge

    @property
    def eligible(self) -> bool:
        minimum_satisfied = (
            self.effective_minimum_days is None or self.effective_minimum_days <= 45
        )
        return minimum_satisfied and not self.no_purge


BARRIER_CASES = tuple(
    _BarrierCase(*values)
    for values in product((None, 30), (None, 60), (False, True), (False, True))
)


async def _seed_terminal_flow_run(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    admin_user_id: UUID,
    classification_id: UUID,
    anchor: datetime,
) -> tuple[Flows, FlowRuns]:
    tenant_space_id = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert tenant_space_id is not None
    space = Spaces(
        name=f"Barrier matrix space {uuid4()}",
        description="Matching classification barrier matrix",
        tenant_id=tenant_id,
        user_id=None,
        tenant_space_id=tenant_space_id,
        security_classification_id=classification_id,
        data_retention_days=None,
    )
    session.add(space)
    await session.flush()
    flow = Flows(
        name=f"Barrier matrix flow {uuid4()}",
        description="Flow retention barrier matrix",
        tenant_id=tenant_id,
        space_id=space.id,
        created_by_user_id=admin_user_id,
        owner_user_id=admin_user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=anchor,
        updated_at=anchor,
    )
    session.add(flow)
    await session.flush()
    session.add(
        FlowVersions(
            flow_id=flow.id,
            version=1,
            tenant_id=tenant_id,
            definition_checksum=f"barrier-matrix-{uuid4()}",
            definition_json={"schema_version": 1, "steps": []},
            created_at=anchor,
            updated_at=anchor,
        )
    )
    await session.flush()
    run = FlowRuns(
        flow_id=flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user_id,
        principal_service_id=None,
        runtime_service_permission=None,
        tenant_id=tenant_id,
        trace_id=uuid4(),
        status="completed",
        started_at=anchor,
        finished_at=anchor,
        input_payload_json={},
        output_payload_json={},
        created_at=anchor,
        updated_at=anchor,
    )
    session.add(run)
    await session.flush()
    return flow, run


@pytest.mark.parametrize("case", BARRIER_CASES, ids=lambda case: case.label)
async def test_matching_classification_barrier_matrix_has_one_policy_result(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    case: _BarrierCase,
) -> None:
    now = datetime.now(timezone.utc)
    run_anchor = now - timedelta(days=45)
    await async_session.execute(
        sa.update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(
            flow_run_history_retention_days=30,
            flow_run_history_minimum_retention_days=(case.organization_minimum_days),
            flow_run_history_no_purge=case.organization_no_purge,
        )
    )
    classification = SecurityClassification(
        name=f"Barrier matrix class {uuid4()}",
        description="Security class 3 follows the ordinary exact match",
        security_level=3,
        tenant_id=test_tenant.id,
    )
    async_session.add(classification)
    await async_session.flush()
    if case.classification_minimum_days is not None or case.classification_no_purge:
        async_session.add(
            FlowClassificationRetentionPolicies(
                tenant_id=test_tenant.id,
                security_classification_id=classification.id,
                data_retention_days=None,
                minimum_retention_days=case.classification_minimum_days,
                no_purge=case.classification_no_purge,
            )
        )
    flow, run = await _seed_terminal_flow_run(
        session=async_session,
        tenant_id=test_tenant.id,
        admin_user_id=admin_user.id,
        classification_id=classification.id,
        anchor=run_anchor,
    )

    retention_service = DataRetentionService(async_session)
    due_run_ids = set(
        (
            await async_session.scalars(
                retention_service._build_due_flow_run_history_purge_query(now=now)
            )
        ).all()
    )
    projected_flow = await FlowRepository(
        session=async_session,
    ).get(flow.id, test_tenant.id)
    preview = await retention_service.preview_flow_retention_organization_change(
        tenant_id=test_tenant.id,
        proposal=FlowRetentionOrganizationProposal(
            flow_run_history_retention_days=30,
            flow_run_history_minimum_retention_days=(case.organization_minimum_days),
            flow_run_history_no_purge=case.organization_no_purge,
            flow_runtime_upload_abandonment_days=None,
        ),
        previewed_at=now,
    )

    assert (run.id in due_run_ids) is case.eligible
    assert preview.run_history.current_eligible_count == int(case.eligible)
    assert preview.run_history.proposed_eligible_count == int(case.eligible)
    assert projected_flow.run_history_retention is not None
    projection = projected_flow.run_history_retention
    assert projection.state == "days"
    assert projection.effective_days == 30
    assert projection.effective_minimum_days == case.effective_minimum_days
    assert projection.no_purge is case.no_purge
    assert projection.policy_conflict is (
        case.effective_minimum_days is not None and case.effective_minimum_days > 30
    )
    assert projection.contributors.organization_minimum_days == (
        case.organization_minimum_days
    )
    assert projection.contributors.classification_minimum_days == (
        case.classification_minimum_days
    )
    assert projection.contributors.organization_no_purge is (case.organization_no_purge)
    assert projection.contributors.classification_no_purge is (
        case.classification_no_purge
    )
    assert projection.activation_sources == ("organization",)
    assert projection.barrier_sources == tuple(
        source
        for source, configured in (
            (
                "organization_minimum",
                case.organization_minimum_days is not None,
            ),
            (
                "classification_minimum",
                case.classification_minimum_days is not None,
            ),
            ("organization_no_purge", case.organization_no_purge),
            ("classification_no_purge", case.classification_no_purge),
        )
        if configured
    )
    assert preview.policy_blockers.run_history_minimum_not_satisfied_count == int(
        case.effective_minimum_days is not None and case.effective_minimum_days > 45
    )
    assert preview.policy_blockers.run_history_no_purge_count == int(
        case.no_purge
        and (case.effective_minimum_days is None or case.effective_minimum_days <= 45)
    )
    assert preview.policy_blockers.run_history_policy_conflict_count == int(
        case.effective_minimum_days is not None and case.effective_minimum_days > 30
    )


async def test_barrier_only_classification_and_child_values_do_not_activate_purge(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
) -> None:
    now = datetime.now(timezone.utc)
    classification = SecurityClassification(
        name=f"Barrier-only class {uuid4()}",
        description="Barrier-only class 3",
        security_level=3,
        tenant_id=test_tenant.id,
    )
    async_session.add(classification)
    await async_session.flush()
    async_session.add(
        FlowClassificationRetentionPolicies(
            tenant_id=test_tenant.id,
            security_classification_id=classification.id,
            data_retention_days=None,
            minimum_retention_days=30,
            no_purge=True,
        )
    )
    flow, run = await _seed_terminal_flow_run(
        session=async_session,
        tenant_id=test_tenant.id,
        admin_user_id=admin_user.id,
        classification_id=classification.id,
        anchor=now - timedelta(days=45),
    )
    await async_session.execute(
        sa.update(Spaces)
        .where(Spaces.id == flow.space_id)
        .values(data_retention_days=1)
    )
    await async_session.execute(
        sa.update(Flows).where(Flows.id == flow.id).values(data_retention_days=1)
    )

    retention_service = DataRetentionService(async_session)
    due_ids = set(
        (
            await async_session.scalars(
                retention_service._build_due_flow_run_history_purge_query(now=now)
            )
        ).all()
    )
    projection = (
        await FlowRepository(async_session).get(flow.id, test_tenant.id)
    ).run_history_retention

    assert run.id not in due_ids
    assert projection is not None
    assert projection.state == "off"
    assert projection.effective_days is None
    assert projection.effective_minimum_days == 30
    assert projection.no_purge is True
    assert projection.activation_sources == ()
    assert projection.barrier_sources == (
        "classification_minimum",
        "classification_no_purge",
    )


async def test_nonmatching_classification_policy_does_not_affect_class_three(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
) -> None:
    now = datetime.now(timezone.utc)
    await async_session.execute(
        sa.update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(flow_run_history_retention_days=30)
    )
    matching = SecurityClassification(
        name=f"Matching class 3 {uuid4()}",
        description="Exact class match",
        security_level=3,
        tenant_id=test_tenant.id,
    )
    other = SecurityClassification(
        name=f"Other class {uuid4()}",
        description="Must not leak policy",
        security_level=2,
        tenant_id=test_tenant.id,
    )
    async_session.add_all((matching, other))
    await async_session.flush()
    async_session.add(
        FlowClassificationRetentionPolicies(
            tenant_id=test_tenant.id,
            security_classification_id=other.id,
            data_retention_days=1,
            minimum_retention_days=90,
            no_purge=True,
        )
    )
    flow, run = await _seed_terminal_flow_run(
        session=async_session,
        tenant_id=test_tenant.id,
        admin_user_id=admin_user.id,
        classification_id=matching.id,
        anchor=now - timedelta(days=45),
    )

    retention_service = DataRetentionService(async_session)
    due_ids = set(
        (
            await async_session.scalars(
                retention_service._build_due_flow_run_history_purge_query(now=now)
            )
        ).all()
    )
    projection = (
        await FlowRepository(async_session).get(flow.id, test_tenant.id)
    ).run_history_retention

    assert run.id in due_ids
    assert projection is not None
    assert projection.effective_days == 30
    assert projection.effective_minimum_days is None
    assert projection.no_purge is False
    assert projection.contributors.classification_days is None


async def test_delete_after_and_minimum_boundaries_are_inclusive_and_conflicted(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
) -> None:
    now = datetime.now(timezone.utc)
    await async_session.execute(
        sa.update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(
            flow_run_history_retention_days=30,
            flow_run_history_minimum_retention_days=60,
        )
    )
    classification = SecurityClassification(
        name=f"Boundary class {uuid4()}",
        description="Exact boundary checks",
        security_level=3,
        tenant_id=test_tenant.id,
    )
    async_session.add(classification)
    await async_session.flush()
    delete_after_flow, delete_after_run = await _seed_terminal_flow_run(
        session=async_session,
        tenant_id=test_tenant.id,
        admin_user_id=admin_user.id,
        classification_id=classification.id,
        anchor=now - timedelta(days=30),
    )
    minimum_flow, minimum_run = await _seed_terminal_flow_run(
        session=async_session,
        tenant_id=test_tenant.id,
        admin_user_id=admin_user.id,
        classification_id=classification.id,
        anchor=now - timedelta(days=60),
    )
    await async_session.execute(
        sa.update(Flows)
        .where(Flows.id.in_((delete_after_flow.id, minimum_flow.id)))
        .values(data_retention_days=1)
    )

    retention_service = DataRetentionService(async_session)
    due_ids = set(
        (
            await async_session.scalars(
                retention_service._build_due_flow_run_history_purge_query(now=now)
            )
        ).all()
    )
    preview = await retention_service.preview_flow_retention_organization_change(
        tenant_id=test_tenant.id,
        proposal=FlowRetentionOrganizationProposal(
            flow_run_history_retention_days=30,
            flow_runtime_upload_abandonment_days=None,
            flow_run_history_minimum_retention_days=60,
            flow_run_history_no_purge=False,
        ),
        previewed_at=now,
    )

    assert delete_after_run.id not in due_ids
    assert minimum_run.id in due_ids
    assert preview.run_history.proposed_eligible_count == 1
    assert preview.policy_blockers.run_history_minimum_not_satisfied_count == 1
    assert preview.policy_blockers.run_history_policy_conflict_count == 2
    assert preview.run_history.earliest_proposed_delete_after_at == (
        minimum_run.finished_at + timedelta(days=1)
    )
    assert preview.run_history.latest_proposed_minimum_not_before_at == (
        delete_after_run.finished_at + timedelta(days=60)
    )
