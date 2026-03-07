from __future__ import annotations

import hashlib
import json
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa

from intric.assistants.assistant import Assistant, AssistantOrigin
from intric.assistants.assistant_service import AssistantService
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.spaces_table import Spaces
from intric.flows.flow import Flow, FlowSparse, FlowStep, JsonObject
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.flows.flow_validators import (
    normalize_legacy_form_schema,
    validate_form_schema,
    validate_steps,
    validate_variable_alias_collisions,
)
from intric.flows.step_config_secrets import encrypt_step_headers_for_storage
from intric.main.exceptions import BadRequestException, NotFoundException
from intric.main.models import NOT_PROVIDED, NotProvided, ResourcePermission
from intric.settings.encryption_service import EncryptionService
from intric.users.user import UserInDB

class FlowService:
    """Tenant-scoped business service for flow lifecycle operations."""

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_version_repo: FlowVersionRepository,
        assistant_service: AssistantService,
        encryption_service: EncryptionService | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_version_repo = flow_version_repo
        self.assistant_service = assistant_service
        self.encryption_service = encryption_service

    async def create_flow(
        self,
        *,
        space_id: UUID,
        name: str,
        steps: list[FlowStep],
        description: str | None = None,
        metadata_json: JsonObject | None = None,
        data_retention_days: int | None = None,
        owner_user_id: UUID | None = None,
    ) -> Flow:
        normalized_metadata = self._normalize_legacy_form_schema(metadata_json)
        self._validate_form_schema(normalized_metadata)
        self._validate_steps(steps, metadata_json=normalized_metadata)
        self._validate_variable_alias_collisions(
            steps=steps,
            metadata_json=normalized_metadata,
        )
        await self._validate_assistant_scope_for_steps(
            space_id=space_id,
            steps=steps,
        )

        normalized_steps = self._normalize_steps_for_tenant(steps)
        persisted_steps = self._prepare_steps_for_persist(normalized_steps)
        flow = Flow(
            id=None,
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            name=name,
            description=description,
            created_by_user_id=self.user.id,
            owner_user_id=owner_user_id or self.user.id,
            published_version=None,
            metadata_json=normalized_metadata,
            data_retention_days=data_retention_days,
            created_at=None,
            updated_at=None,
            steps=persisted_steps,
        )
        return await self.flow_repo.create(flow=flow, tenant_id=self.user.tenant_id)

    async def get_flow(self, flow_id: UUID) -> Flow:
        return await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)

    async def list_flows(
        self,
        *,
        space_id: UUID,
        sparse: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowSparse] | list[Flow]:
        if sparse:
            return await self.flow_repo.get_sparse_by_space(
                space_id=space_id,
                tenant_id=self.user.tenant_id,
                limit=limit,
                offset=offset,
            )
        return await self.flow_repo.get_by_space(
            space_id=space_id,
            tenant_id=self.user.tenant_id,
            limit=limit,
            offset=offset,
        )

    async def update_flow(
        self,
        *,
        flow_id: UUID,
        name: str | NotProvided = NOT_PROVIDED,
        description: str | None | NotProvided = NOT_PROVIDED,
        steps: list[FlowStep] | None = None,
        metadata_json: JsonObject | None | NotProvided = NOT_PROVIDED,
        data_retention_days: int | None | NotProvided = NOT_PROVIDED,
    ) -> Flow:
        existing = await self.get_flow(flow_id)
        if existing.published_version is not None:
            raise BadRequestException("Cannot mutate a published flow. Unpublish first.")

        next_steps = steps if steps is not None else existing.steps
        await self._validate_assistant_scope_for_steps(
            space_id=existing.space_id,
            steps=next_steps,
            owning_flow_id=existing.id,
        )

        next_metadata = self._normalize_legacy_form_schema(existing.metadata_json)
        if metadata_json is not NOT_PROVIDED:
            next_metadata = self._normalize_legacy_form_schema(cast(JsonObject | None, metadata_json))
        self._validate_form_schema(next_metadata)
        self._validate_steps(next_steps, metadata_json=next_metadata)
        self._validate_variable_alias_collisions(
            steps=next_steps,
            metadata_json=next_metadata,
        )

        next_retention = existing.data_retention_days
        if data_retention_days is not NOT_PROVIDED:
            next_retention = data_retention_days

        normalized_steps = self._normalize_steps_for_tenant(next_steps)
        persisted_steps = self._prepare_steps_for_persist(normalized_steps)
        updated = existing.model_copy(
            deep=True,
            update={
                "name": existing.name if name is NOT_PROVIDED else name,
                "description": (
                    existing.description
                    if description is NOT_PROVIDED
                    else description
                ),
                "steps": persisted_steps,
                "metadata_json": next_metadata,
                "data_retention_days": next_retention,
            },
        )
        return await self.flow_repo.update(flow=updated, tenant_id=self.user.tenant_id)

    async def delete_flow(self, flow_id: UUID) -> None:
        await self.flow_repo.delete(flow_id=flow_id, tenant_id=self.user.tenant_id)

    async def create_flow_assistant(
        self,
        *,
        flow_id: UUID,
        name: str,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        return await self.assistant_service.create_assistant(
            name=name,
            space_id=flow.space_id,
            hidden=True,
            origin=AssistantOrigin.FLOW_MANAGED,
            managing_flow_id=flow.id,
        )

    async def get_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        assistant, permissions = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return assistant, permissions

    async def update_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
        **changes: Any,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return await self.assistant_service.update_assistant(
            assistant_id=assistant_id,
            include_hidden=True,
            **changes,
        )

    async def delete_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
    ) -> None:
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        await self.assistant_service.delete_assistant(assistant_id)

    async def unpublish_flow(self, *, flow_id: UUID) -> Flow:
        flow = await self.get_flow(flow_id)
        if flow.published_version is None:
            raise BadRequestException("Flow is not published.")
        updated = flow.model_copy(update={"published_version": None}, deep=True)
        return await self.flow_repo.update(updated, tenant_id=self.user.tenant_id)

    async def publish_flow(self, *, flow_id: UUID) -> Flow:
        flow = await self.get_flow(flow_id)
        normalized_metadata = self._normalize_legacy_form_schema(flow.metadata_json)
        self._validate_form_schema(normalized_metadata)
        self._validate_publishable(flow, metadata_json=normalized_metadata)
        self._validate_variable_alias_collisions(
            steps=flow.steps,
            metadata_json=normalized_metadata,
        )
        await self._validate_assistant_scope_for_steps(
            space_id=flow.space_id,
            steps=flow.steps,
            owning_flow_id=flow.id,
        )

        latest = await self.flow_version_repo.get_latest(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        next_version = 1 if latest is None else latest.version + 1

        definition = self._build_definition(flow)
        checksum = self._definition_checksum(definition)
        await self.flow_version_repo.create(
            flow_id=flow_id,
            version=next_version,
            definition_checksum=checksum,
            definition_json=definition,
            tenant_id=self.user.tenant_id,
        )

        updated = flow.model_copy(
            update={
                "published_version": next_version,
                "metadata_json": normalized_metadata,
            },
            deep=True,
        )
        return await self.flow_repo.update(updated, tenant_id=self.user.tenant_id)

    def _validate_publishable(self, flow: Flow, *, metadata_json: JsonObject | None) -> None:
        self._validate_steps(flow.steps, metadata_json=metadata_json)
        if not flow.steps:
            raise BadRequestException("Flow must contain at least one step before publish.")

    def _validate_steps(
        self,
        steps: list[FlowStep],
        *,
        metadata_json: JsonObject | None = None,
    ) -> None:
        validate_steps(steps, metadata_json=metadata_json)

    def _validate_form_schema(self, metadata_json: JsonObject | None) -> None:
        validate_form_schema(metadata_json)

    def _normalize_legacy_form_schema(self, metadata_json: JsonObject | None) -> JsonObject | None:
        return normalize_legacy_form_schema(metadata_json)

    def _validate_variable_alias_collisions(
        self,
        *,
        steps: list[FlowStep],
        metadata_json: JsonObject | None,
    ) -> None:
        validate_variable_alias_collisions(
            steps=steps,
            metadata_json=metadata_json,
        )

    async def _validate_assistant_scope_for_steps(
        self,
        *,
        space_id: UUID,
        steps: list[FlowStep],
        owning_flow_id: UUID | None = None,
    ) -> None:
        assistant_ids = {step.assistant_id for step in steps}
        if not assistant_ids:
            return

        rows = await self.flow_repo.session.execute(
            sa.select(Assistants.id, Assistants.origin, Assistants.managing_flow_id)
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(Assistants.id.in_(assistant_ids))
            .where(Assistants.space_id == space_id)
            .where(Spaces.tenant_id == self.user.tenant_id)
        )
        assistant_rows = rows.all()
        allowed_ids = {row.id for row in assistant_rows}
        missing = assistant_ids - allowed_ids
        if missing:
            raise BadRequestException(
                "One or more steps reference assistants outside the selected space or tenant."
            )

        if owning_flow_id is None:
            return

        non_owned = [
            row.id
            for row in assistant_rows
            if row.origin != AssistantOrigin.FLOW_MANAGED.value
            or row.managing_flow_id != owning_flow_id
        ]
        if non_owned:
            raise BadRequestException(
                "Flow steps must reference flow-managed assistants owned by the flow."
            )

    def _normalize_steps_for_tenant(self, steps: list[FlowStep]) -> list[FlowStep]:
        return [
            step.model_copy(
                update={
                    "flow_id": step.flow_id,
                    "tenant_id": self.user.tenant_id,
                },
                deep=True,
            )
            for step in steps
        ]

    def _prepare_steps_for_persist(self, steps: list[FlowStep]) -> list[FlowStep]:
        return [
            step.model_copy(
                update={
                    "input_config": encrypt_step_headers_for_storage(
                        config=step.input_config,
                        encryption_service=self.encryption_service,
                    ),
                    "output_config": encrypt_step_headers_for_storage(
                        config=step.output_config,
                        encryption_service=self.encryption_service,
                    ),
                },
                deep=True,
            )
            for step in steps
        ]

    def _build_definition(self, flow: Flow) -> JsonObject:
        return {
            "flow_id": str(flow.id),
            "name": flow.name,
            "description": flow.description,
            "metadata_json": flow.metadata_json,
            "steps": [
                self._step_to_definition(step)
                for step in sorted(flow.steps, key=lambda item: item.step_order)
            ],
        }

    def _step_to_definition(self, step: FlowStep) -> JsonObject:
        return {
            "step_id": str(step.id) if step.id is not None else None,
            "step_order": step.step_order,
            "assistant_id": str(step.assistant_id),
            "user_description": step.user_description,
            "input_source": step.input_source,
            "input_type": step.input_type,
            "input_contract": step.input_contract,
            "output_mode": step.output_mode,
            "output_type": step.output_type,
            "output_contract": step.output_contract,
            "input_bindings": step.input_bindings,
            "output_classification_override": step.output_classification_override,
            "mcp_policy": step.mcp_policy,
            "input_config": step.input_config,
            "output_config": step.output_config,
        }

    def _ensure_flow_is_mutable(self, flow: Flow) -> None:
        if flow.published_version is not None:
            raise BadRequestException("Cannot mutate assistant of a published flow")

    def _assert_flow_assistant_owned_by_flow(self, *, flow: Flow, assistant: Assistant) -> None:
        if assistant.origin != AssistantOrigin.FLOW_MANAGED:
            raise NotFoundException("Assistant is not flow-managed.")
        if assistant.managing_flow_id != flow.id:
            raise NotFoundException("Assistant belongs to a different flow.")

    def _definition_checksum(self, definition: JsonObject) -> str:
        serialized = json.dumps(
            definition,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
