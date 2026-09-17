"""Database-only projections for the operator capacity report."""

from collections.abc import AsyncIterator
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from eneo.apps.apps.app_factory import AppFactory
from eneo.assistants.assistant_factory import AssistantFactory
from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.completion_models.domain.completion_model_repo import (
    CompletionModelRepository,
)
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import FlowRuns, Flows
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow import FlowRunStatusSnapshot, FlowSparse, FlowVersion
from eneo.flows.enums import FlowRunStatus, is_terminal_flow_run_status
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.prompts.prompt_factory import PromptFactory
from eneo.spaces.space import Space
from eneo.spaces.space_factory import SpaceFactory
from eneo.templates.app_template.app_template_factory import AppTemplateFactory
from eneo.templates.assistant_template.assistant_template_factory import (
    AssistantTemplateFactory,
)
from eneo.tenants.tenant import TenantInDB
from eneo.tenants.tenant_repo import TenantRepository


class ModelCapacityReadinessRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def tenants(self, tenant_id: UUID | None) -> AsyncIterator[TenantInDB]:
        statement = sa.select(Tenants.id).order_by(Tenants.id)
        if tenant_id is not None:
            statement = statement.where(Tenants.id == tenant_id)
        rows = await self.session.stream_scalars(
            statement.execution_options(yield_per=100)
        )
        async for identity in rows:
            owner = await TenantRepository(self.session).get(identity)
            if owner is None:
                raise ValueError("Tenant disappeared")
            yield owner

    async def active_provider_ids(self, owner: TenantInDB) -> set[UUID]:
        rows = await self.session.stream_scalars(
            sa.select(ModelProviders.id)
            .where(
                ModelProviders.tenant_id == owner.id,
                ModelProviders.is_active.is_(True),
            )
            .execution_options(yield_per=100)
        )
        return {identity async for identity in rows}

    async def builder_spaces(self, owner: TenantInDB) -> AsyncIterator[Space]:
        model_rows = await self.session.stream(
            sa.select(
                CompletionModels, ModelProviders.name, ModelProviders.provider_type
            )
            .outerjoin(
                ModelProviders, CompletionModels.provider_id == ModelProviders.id
            )
            .where(
                sa.or_(
                    CompletionModels.tenant_id == owner.id,
                    CompletionModels.tenant_id.is_(None),
                ),
                CompletionModels.deleted_at.is_(None),
            )
            .options(
                selectinload(CompletionModels.security_classification).selectinload(
                    SecurityClassification.tenant
                )
            )
            .execution_options(yield_per=100)
        )
        models = [
            CompletionModel.create_from_db(
                row, owner, provider_name=name, provider_type=kind
            )
            async for row, name, kind in model_rows
        ]
        factory = SpaceFactory(
            AssistantFactory(PromptFactory(), AssistantTemplateFactory()),
            AppFactory(AppTemplateFactory()),
        )
        # The factory owns personal/shared model selection. Unrelated resources
        # stay unloaded: this projection cannot fetch attachments or credentials.
        rows = await self.session.stream_scalars(
            sa.select(Spaces)
            .where(Spaces.tenant_id == owner.id)
            .order_by(Spaces.id)
            .options(
                noload("*"),
                selectinload(Spaces.completion_models_mapping),
                selectinload(Spaces.security_classification).selectinload(
                    SecurityClassification.tenant
                ),
            )
            .execution_options(yield_per=100)
        )
        async for row in rows:
            yield factory.create_space_from_db(
                row,
                user=None,
                completion_models=models,
                security_classification=row.security_classification,
            )

    async def published_flows(self, owner: TenantInDB) -> AsyncIterator[FlowSparse]:
        rows = await self.session.stream(
            sa.select(Flows.id, Flows.space_id, Flows.published_version)
            .where(
                Flows.tenant_id == owner.id,
                Flows.deleted_at.is_(None),
                Flows.published_version.is_not(None),
            )
            .order_by(Flows.id)
            .execution_options(yield_per=100)
        )
        async for identity, space_id, number in rows:
            yield FlowSparse(
                id=identity,
                tenant_id=owner.id,
                space_id=space_id,
                name="",
                published_version=number,
            )

    async def runs_for_tenant(
        self, owner: TenantInDB
    ) -> AsyncIterator[FlowRunStatusSnapshot]:
        statuses = [
            status.value
            for status in FlowRunStatus
            if not is_terminal_flow_run_status(status)
        ]
        rows = await self.session.stream(
            sa.select(
                FlowRuns.id,
                FlowRuns.flow_id,
                FlowRuns.flow_version,
                FlowRuns.trace_id,
                FlowRuns.status,
                FlowRuns.created_at,
                FlowRuns.updated_at,
            )
            .where(FlowRuns.tenant_id == owner.id, FlowRuns.status.in_(statuses))
            .order_by(FlowRuns.id)
            .execution_options(yield_per=100)
        )
        async for identity, flow_id, number, trace_id, status, created, updated in rows:
            yield FlowRunStatusSnapshot(
                id=identity,
                flow_id=flow_id,
                flow_version=number,
                trace_id=trace_id,
                tenant_id=owner.id,
                status=FlowRunStatus(status),
                created_at=created,
                updated_at=updated,
            )

    async def get_version(
        self, owner: TenantInDB, flow_id: UUID, number: int
    ) -> FlowVersion:
        return await FlowVersionRepository(self.session).get(flow_id, number, owner.id)

    async def assistant_model(
        self, owner: TenantInDB, assistant_id: UUID
    ) -> CompletionModel | None:
        # Runtime resolves the current assistant in its tenant-scoped space;
        # published assistant hashes do not freeze a completion model selection.
        row = (
            await self.session.execute(
                sa.select(Assistants.completion_model_id)
                .join(Spaces, Spaces.id == Assistants.space_id)
                .where(Assistants.id == assistant_id, Spaces.tenant_id == owner.id)
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Assistant not found")
        if row[0] is None:
            return None
        return await CompletionModelRepository(
            session=self.session, tenant=owner
        ).one_or_none(row[0])
