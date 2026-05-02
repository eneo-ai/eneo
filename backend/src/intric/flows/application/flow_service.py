from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from intric.assistants.assistant import Assistant, AssistantOrigin
from intric.assistants.assistant_service import AssistantService
from intric.files.file_models import File
from intric.files.file_repo import FileRepository
from intric.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
)
from intric.flows.domain.flow import Flow, FlowSparse, FlowStep, JsonObject
from intric.flows.flow_care_data_policy import validate_flow_care_data_policy
from intric.flows.flow_security_classification import (
    evaluate_step_security_classification,
)
from intric.flows.flow_template_asset_repo import FlowTemplateAssetRepository
from intric.flows.flow_validators import (
    normalize_legacy_form_schema,
    validate_form_schema,
    validate_steps,
    validate_variable_alias_collisions,
)
from intric.flows.http_transport import (
    HttpAuthoredConfig,
    encrypt_authored_config,
    is_authored_config,
    merge_secrets_on_update,
)
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.published_definition import (
    build_published_definition_json,
    published_definition_checksum,
)
from intric.flows.runtime.docx_template_runtime import (
    extract_docx_template_text_preview,
    inspect_docx_template_bytes,
)
from intric.flows.step_config_secrets import encrypt_step_headers_for_storage
from intric.main.exceptions import BadRequestException, NotFoundException
from intric.main.models import NOT_PROVIDED, NotProvided, ResourcePermission
from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.settings.encryption_service import EncryptionService
from intric.spaces.space_service import SpaceService
from intric.users.user import UserInDB


class FlowService:
    """Tenant-scoped business service for flow lifecycle operations."""

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_version_repo: FlowVersionRepository,
        assistant_service: AssistantService,
        file_repo: FileRepository,
        template_asset_repo: FlowTemplateAssetRepository | None = None,
        encryption_service: EncryptionService | None = None,
        space_service: SpaceService | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_version_repo = flow_version_repo
        self.assistant_service = assistant_service
        self.file_repo = file_repo
        self.template_asset_repo = template_asset_repo
        self.encryption_service = encryption_service
        self.space_service = space_service

    def _require_template_asset_repo(self) -> FlowTemplateAssetRepository:
        if self.template_asset_repo is None:
            raise RuntimeError(
                "FlowService requires template_asset_repo for template asset operations."
            )
        return self.template_asset_repo

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
        await self._validate_step_security_classification_for_steps(
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
        published_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowSparse] | list[Flow]:
        if sparse:
            return await self.flow_repo.get_sparse_by_space(
                space_id=space_id,
                tenant_id=self.user.tenant_id,
                published_only=published_only,
                limit=limit,
                offset=offset,
            )
        return await self.flow_repo.get_by_space(
            space_id=space_id,
            tenant_id=self.user.tenant_id,
            published_only=published_only,
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
        expected_revision: int | None = None,
    ) -> Flow:
        existing = await self.get_flow(flow_id)
        if existing.published_version is not None:
            raise BadRequestException(
                "Cannot mutate a published flow. Unpublish first."
            )

        next_steps = steps if steps is not None else existing.steps
        await self._validate_assistant_scope_for_steps(
            space_id=existing.space_id,
            steps=next_steps,
            owning_flow_id=existing.id,
        )
        await self._validate_step_security_classification_for_steps(
            space_id=existing.space_id,
            steps=next_steps,
        )

        next_metadata = self._normalize_legacy_form_schema(existing.metadata_json)
        if metadata_json is not NOT_PROVIDED:
            next_metadata = self._normalize_legacy_form_schema(
                cast(JsonObject | None, metadata_json)
            )
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
        merged_steps = self._merge_step_secrets(normalized_steps, existing.steps)
        persisted_steps = self._prepare_steps_for_persist(merged_steps)
        updated = existing.model_copy(
            deep=True,
            update={
                "name": existing.name if name is NOT_PROVIDED else name,
                "description": (
                    existing.description if description is NOT_PROVIDED else description
                ),
                "steps": persisted_steps,
                "metadata_json": next_metadata,
                "data_retention_days": next_retention,
            },
        )
        return await self.flow_repo.update(
            flow=updated,
            tenant_id=self.user.tenant_id,
            expected_revision=expected_revision,
        )

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
        assistant_service = cast(Any, self.assistant_service)
        return cast(
            tuple[Assistant, list[ResourcePermission]],
            await assistant_service.create_assistant(
                name=name,
                space_id=flow.space_id,
                hidden=True,
                origin=AssistantOrigin.FLOW_MANAGED,
                managing_flow_id=flow.id,
            ),
        )

    async def get_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        assistant, permissions = await self.assistant_service.get_assistant(
            assistant_id
        )
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return assistant, permissions

    async def get_flow_assistant_snapshots(
        self, flow: Flow
    ) -> dict[UUID, dict[str, Any]]:
        assistant_ids = list(dict.fromkeys(step.assistant_id for step in flow.steps))
        return await self.flow_repo.get_assistant_snapshots(
            assistant_ids=assistant_ids,
            tenant_id=self.user.tenant_id,
        )

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
        await self._validate_flow_assistant_security_change(
            flow=flow,
            assistant=assistant,
            changes=changes,
        )
        assistant_service = cast(Any, self.assistant_service)
        return cast(
            tuple[Assistant, list[ResourcePermission]],
            await assistant_service.update_assistant(
                assistant_id=assistant_id,
                include_hidden=True,
                **changes,
            ),
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

    async def inspect_template_file(
        self,
        *,
        flow_id: UUID,
        file_id: UUID,
    ) -> dict[str, Any]:
        _, template_file = await self._get_template_asset_file(
            flow_id=flow_id,
            asset_id=file_id,
        )
        return {
            "asset_id": file_id,
            "file_id": template_file.id,
            "file_name": template_file.name,
            "placeholders": self._inspect_docx_template(template_file),
            "extracted_text_preview": extract_docx_template_text_preview(
                template_file.blob or b""
            ),
        }

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
        await self._validate_step_security_classification_for_steps(
            space_id=flow.space_id,
            steps=flow.steps,
        )

        latest = await self.flow_version_repo.get_latest(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        next_version = 1 if latest is None else latest.version + 1

        definition = await self._build_definition(flow)
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

    def _validate_publishable(
        self, flow: Flow, *, metadata_json: JsonObject | None
    ) -> None:
        self._validate_steps(
            flow.steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=True,
        )
        if not flow.steps:
            raise BadRequestException(
                "Flow must contain at least one step before publish."
            )

    def _validate_steps(
        self,
        steps: list[FlowStep],
        *,
        metadata_json: JsonObject | None = None,
        require_complete_template_fill_config: bool = False,
    ) -> None:
        validate_steps(
            steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=require_complete_template_fill_config,
        )

    def _validate_form_schema(self, metadata_json: JsonObject | None) -> None:
        validate_form_schema(metadata_json)
        validate_flow_care_data_policy(metadata_json)

    def _normalize_legacy_form_schema(
        self, metadata_json: JsonObject | None
    ) -> JsonObject | None:
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
        require_owned_by_flow: bool = False,
    ) -> None:
        assistant_ids = {step.assistant_id for step in steps}
        if not assistant_ids:
            return

        assistant_rows = await self.flow_repo.get_assistant_scope_rows(
            assistant_ids=assistant_ids,
            space_id=space_id,
            tenant_id=self.user.tenant_id,
        )
        allowed_ids = {row.id for row in assistant_rows}
        missing = assistant_ids - allowed_ids
        if missing:
            raise BadRequestException(
                "One or more steps reference assistants outside the selected space or tenant."
            )

        if owning_flow_id is None:
            if not require_owned_by_flow:
                return
            raise BadRequestException(
                "Flow steps must reference flow-managed assistants owned by the flow."
            )

        non_owned = [
            row.id
            for row in assistant_rows
            if row.origin != AssistantOrigin.FLOW_MANAGED
            or row.managing_flow_id != owning_flow_id
        ]
        if non_owned:
            raise BadRequestException(
                "Flow steps must reference flow-managed assistants owned by the flow."
            )

    async def _validate_step_security_classification_for_steps(
        self,
        *,
        space_id: UUID,
        steps: list[FlowStep],
    ) -> None:
        if self.space_service is None or not steps:
            return

        space = await self.space_service.get_space(space_id)
        assistants_by_id: dict[UUID, Assistant] = {}
        for step in sorted(steps, key=lambda item: item.step_order):
            assistant, _ = await self.assistant_service.get_assistant(step.assistant_id)
            assistants_by_id[step.assistant_id] = assistant
        self._validate_step_security_classification_with_assistants(
            steps=steps,
            assistants_by_id=assistants_by_id,
            space=space,
        )

    def _validate_step_security_classification_with_assistants(
        self,
        *,
        steps: list[FlowStep],
        assistants_by_id: dict[UUID, Any],
        space: Any,
    ) -> None:
        prior_output_levels: dict[int, int | None] = {}
        for step in sorted(steps, key=lambda item: item.step_order):
            assistant = assistants_by_id[step.assistant_id]
            evaluation = evaluate_step_security_classification(
                step_order=step.step_order,
                input_source=str(step.input_source),
                output_classification_override=step.output_classification_override,
                prior_output_levels_by_order=prior_output_levels,
                assistant=assistant,
                space=space,
            )
            prior_output_levels[step.step_order] = evaluation.effective_output_level

    async def _validate_flow_assistant_security_change(
        self,
        *,
        flow: Flow,
        assistant: Assistant,
        changes: dict[str, Any],
    ) -> None:
        if self.space_service is None:
            return

        relevant_fields = {
            "completion_model_id",
            "groups",
            "websites",
            "integration_knowledge_ids",
            "mcp_server_ids",
        }
        if relevant_fields.isdisjoint(changes.keys()):
            return

        if not any(step.assistant_id == assistant.id for step in flow.steps):
            return

        space = await self.space_service.get_space(flow.space_id)
        candidate_assistant = (
            self._build_candidate_flow_assistant_for_security_validation(
                assistant=assistant,
                space=space,
                changes=changes,
            )
        )
        assistants_by_id: dict[UUID, Any] = {assistant.id: candidate_assistant}
        for step in sorted(flow.steps, key=lambda item: item.step_order):
            if step.assistant_id in assistants_by_id:
                continue
            current_assistant, _ = await self.assistant_service.get_assistant(
                step.assistant_id
            )
            assistants_by_id[step.assistant_id] = current_assistant

        self._validate_step_security_classification_with_assistants(
            steps=flow.steps,
            assistants_by_id=assistants_by_id,
            space=space,
        )

    def _build_candidate_flow_assistant_for_security_validation(
        self,
        *,
        assistant: Assistant,
        space: Any,
        changes: dict[str, Any],
    ) -> Any:
        completion_model = assistant.completion_model
        if "completion_model_id" in changes:
            next_completion_model_id = changes["completion_model_id"]
            completion_model = (
                space.get_completion_model(next_completion_model_id)
                if next_completion_model_id is not None
                else None
            )

        collections = assistant.collections
        if "groups" in changes and changes["groups"] is not None:
            collections = [
                space.get_collection(group_id) for group_id in changes["groups"]
            ]

        websites = assistant.websites
        if "websites" in changes and changes["websites"] is not None:
            websites = [
                space.get_website(website_id) for website_id in changes["websites"]
            ]

        integration_knowledge_list = assistant.integration_knowledge_list
        if (
            "integration_knowledge_ids" in changes
            and changes["integration_knowledge_ids"] is not None
        ):
            integration_knowledge_list = [
                space.get_integration_knowledge(integration_knowledge_id)
                for integration_knowledge_id in changes["integration_knowledge_ids"]
            ]

        mcp_servers: list[MCPServer] = assistant.mcp_servers
        if "mcp_server_ids" in changes and changes["mcp_server_ids"] is not None:
            mcp_servers = []
            unavailable_mcp_server_ids: list[str] = []
            for mcp_server_id in changes["mcp_server_ids"]:
                try:
                    mcp_servers.append(
                        cast(MCPServer, space.get_mcp_server(mcp_server_id))
                    )
                except NotFoundException:
                    unavailable_mcp_server_ids.append(str(mcp_server_id))
            if unavailable_mcp_server_ids:
                raise BadRequestException(
                    "MCP server(s) are not available in this flow's space.",
                    code="flow_mcp_server_not_available",
                    context={"mcp_server_ids": unavailable_mcp_server_ids},
                )

        return SimpleNamespace(
            completion_model=completion_model,
            collections=collections,
            websites=websites,
            integration_knowledge_list=integration_knowledge_list,
            mcp_servers=mcp_servers,
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
                    "input_config": self._encrypt_config(step.input_config),
                    "output_config": self._encrypt_config(step.output_config),
                },
                deep=True,
            )
            for step in steps
        ]

    def _encrypt_config(self, config: JsonObject | None) -> JsonObject | None:
        if config is None:
            return config
        if is_authored_config(config):
            authored = HttpAuthoredConfig.model_validate(config)
            encrypted = encrypt_authored_config(authored, self.encryption_service)
            return encrypted.model_dump(mode="json")
        return encrypt_step_headers_for_storage(
            config=config, encryption_service=self.encryption_service
        )

    def _merge_step_secrets(
        self,
        incoming_steps: list[FlowStep],
        stored_steps: list[FlowStep],
    ) -> list[FlowStep]:
        """Merge sentinel secret values from incoming with stored encrypted values."""
        stored_by_order = {s.step_order: s for s in stored_steps}
        result: list[FlowStep] = []
        for step in incoming_steps:
            stored = stored_by_order.get(step.step_order)
            input_config = self._merge_config_secrets(
                step.input_config, stored.input_config if stored else None
            )
            output_config = self._merge_config_secrets(
                step.output_config, stored.output_config if stored else None
            )
            result.append(
                step.model_copy(
                    update={
                        "input_config": input_config,
                        "output_config": output_config,
                    },
                    deep=True,
                )
            )
        return result

    @staticmethod
    def _merge_config_secrets(
        incoming: JsonObject | None, stored: JsonObject | None
    ) -> JsonObject | None:
        if incoming is None or not is_authored_config(incoming):
            return incoming
        if stored is None or not is_authored_config(stored):
            return incoming
        incoming_config = HttpAuthoredConfig.model_validate(incoming)
        stored_config = HttpAuthoredConfig.model_validate(stored)
        merged = merge_secrets_on_update(incoming_config, stored_config)
        return merged.model_dump(mode="json")

    async def _build_definition(self, flow: Flow) -> JsonObject:
        return build_published_definition_json(
            flow_id=cast(UUID, flow.id),
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[
                await self._step_to_definition(step, flow=flow)
                for step in sorted(flow.steps, key=lambda item: item.step_order)
            ],
        )

    async def _step_to_definition(
        self,
        step: FlowStep,
        *,
        flow: Flow,
    ) -> JsonObject:
        output_config = step.output_config
        if step.output_mode == "template_fill":
            output_config = await self._prepare_template_output_config_for_publish(
                step,
                flow=flow,
            )
        assistant_payload: Any = await self.assistant_service.get_assistant(
            step.assistant_id
        )
        assistant = cast(
            Any | None,
            assistant_payload[0]
            if isinstance(assistant_payload, tuple) and assistant_payload
            else None,
        )
        mcp_server_entities: list[Any] = []
        if assistant is not None:
            assistant_mcp_servers = assistant.mcp_servers
            if isinstance(assistant_mcp_servers, list):
                mcp_server_entities = cast(list[Any], assistant_mcp_servers)
        mcp_servers: list[dict[str, str]] = [
            {"id": str(server.id), "name": server.name}
            for server in mcp_server_entities
        ]
        mcp_tools_enabled: list[dict[str, str]] = []
        for server in mcp_server_entities:
            server_tools = cast(list[Any], getattr(server, "tools", []) or [])
            for tool in server_tools:
                if cast(bool, getattr(tool, "is_enabled", False)) is not True:
                    continue
                mcp_tools_enabled.append(
                    {
                        "tool_id": str(tool.id),
                        "server_id": str(server.id),
                        "name": tool.name,
                    }
                )
        assistant_snapshot = build_assistant_execution_snapshot(
            assistant=assistant,
            mcp_server_entities=mcp_server_entities,
        )
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
            "mcp_servers": mcp_servers,
            "mcp_tools_enabled": mcp_tools_enabled,
            "assistant_snapshot": assistant_snapshot,
            "input_config": step.input_config,
            "output_config": output_config,
            "review_policy": (
                step.review_policy.model_dump(mode="json")
                if step.review_policy is not None
                else None
            ),
        }

    def _ensure_flow_is_mutable(self, flow: Flow) -> None:
        if flow.published_version is not None:
            raise BadRequestException("Cannot mutate assistant of a published flow")

    def _assert_flow_assistant_owned_by_flow(
        self, *, flow: Flow, assistant: Assistant
    ) -> None:
        if assistant.origin != AssistantOrigin.FLOW_MANAGED:
            raise NotFoundException("Assistant is not flow-managed.")
        if assistant.managing_flow_id != flow.id:
            raise NotFoundException("Assistant belongs to a different flow.")

    def _definition_checksum(self, definition: JsonObject) -> str:
        return published_definition_checksum(definition)

    async def _prepare_template_output_config_for_publish(
        self,
        step: FlowStep,
        *,
        flow: Flow,
    ) -> dict[str, Any]:
        if not isinstance(step.output_config, dict):
            raise BadRequestException(
                f"Step {step.step_order}: output_config must be an object for output_mode 'template_fill'."
            )

        template_asset, template_file = await self._resolve_template_asset_reference(
            step=step,
            flow=flow,
        )
        placeholders = self._inspect_docx_template(template_file)
        placeholder_names = self._placeholder_names(placeholders)
        bindings = step.output_config.get("bindings")
        if not isinstance(bindings, dict):
            raise BadRequestException(
                f"Step {step.step_order}: output_config.bindings must be an object."
            )
        missing = [name for name in placeholder_names if name not in bindings]
        if missing:
            raise BadRequestException(
                f"Step {step.step_order}: template placeholders are missing bindings: {', '.join(missing)}."
            )
        for placeholder, binding in cast(JsonObject, bindings).items():
            if not placeholder.strip():
                raise BadRequestException(
                    f"Step {step.step_order}: output_config.bindings keys must be non-empty strings."
                )
            if not isinstance(binding, str):
                raise BadRequestException(
                    f"Step {step.step_order}: binding '{placeholder}' must be a template expression or an explicit empty string."
                )

        next_output_config = dict(step.output_config)
        next_output_config["template_asset_id"] = str(template_asset.id)
        next_output_config["template_file_id"] = str(template_file.id)
        next_output_config["template_checksum"] = template_file.checksum
        next_output_config["template_name"] = template_file.name
        next_output_config["placeholders"] = placeholder_names
        return next_output_config

    async def _get_template_asset_file(
        self,
        *,
        flow_id: UUID | None,
        asset_id: UUID,
    ) -> tuple[Any, File]:
        template_asset_repo = self._require_template_asset_repo()
        asset = await template_asset_repo.get(
            asset_id=asset_id,
            tenant_id=self.user.tenant_id,
        )
        if flow_id is not None and asset.flow_id != flow_id:
            raise NotFoundException("Flow template asset not found.")
        file = await self.file_repo.get_by_id(file_id=asset.file_id)
        if file.tenant_id != self.user.tenant_id:
            raise NotFoundException("Flow template asset file not found.")
        if file.blob is None:
            raise BadRequestException(
                "The selected DOCX template could not be read because the file content is missing. Upload the template again or choose another DOCX file.",
                code="flow_template_missing_content",
            )
        return asset, file

    async def _resolve_template_asset_reference(
        self,
        *,
        step: FlowStep,
        flow: Flow,
    ) -> tuple[Any, File]:
        if not isinstance(step.output_config, dict):
            raise BadRequestException(
                f"Step {step.step_order}: output_config must be an object for output_mode 'template_fill'."
            )

        template_asset_id_raw = step.output_config.get("template_asset_id")
        if template_asset_id_raw not in (None, ""):
            try:
                template_asset_id = UUID(str(template_asset_id_raw))
            except Exception as exc:
                raise BadRequestException(
                    f"Step {step.step_order}: output_config.template_asset_id must be a UUID."
                ) from exc
            try:
                return await self._get_template_asset_file(
                    flow_id=flow.id,
                    asset_id=template_asset_id,
                )
            except NotFoundException as exc:
                raise self._template_not_accessible_error(
                    step_order=step.step_order
                ) from exc

        template_file_id_raw = step.output_config.get("template_file_id")
        if template_file_id_raw in (None, ""):
            raise BadRequestException(
                f"Step {step.step_order}: output_config.template_asset_id or template_file_id must be configured."
            )
        try:
            template_file_id = UUID(str(template_file_id_raw))
        except Exception as exc:
            raise BadRequestException(
                f"Step {step.step_order}: output_config.template_file_id must be a UUID."
            ) from exc
        try:
            if flow.id is None:
                raise BadRequestException(
                    f"Step {step.step_order}: flow id missing while resolving DOCX template asset."
                )
            template_asset_repo = self._require_template_asset_repo()
            asset = await template_asset_repo.get_by_flow_file(
                flow_id=flow.id,
                file_id=template_file_id,
                tenant_id=self.user.tenant_id,
            )
        except NotFoundException:
            try:
                asset = await self._promote_legacy_template_file_to_asset(
                    flow=flow,
                    file_id=template_file_id,
                )
            except NotFoundException as exc:
                raise self._template_not_accessible_error(
                    step_order=step.step_order
                ) from exc
        try:
            return await self._get_template_asset_file(
                flow_id=flow.id,
                asset_id=asset.id,
            )
        except NotFoundException as exc:
            raise self._template_not_accessible_error(
                step_order=step.step_order
            ) from exc

    def _inspect_docx_template(self, file: File) -> list[dict[str, Any]]:
        return inspect_docx_template_bytes(file.blob or b"", filename=file.name)

    @staticmethod
    def _template_not_accessible_error(*, step_order: int) -> BadRequestException:
        return BadRequestException(
            f"Step {step_order}: selected DOCX template is no longer available for this flow. Upload the template again or choose another DOCX file.",
            code="flow_template_not_accessible",
        )

    async def _promote_legacy_template_file_to_asset(
        self,
        *,
        flow: Flow,
        file_id: UUID,
    ) -> Any:
        template_file = await self.file_repo.get_by_id(file_id=file_id)
        if template_file.tenant_id != self.user.tenant_id:
            raise NotFoundException("Flow template asset file not found.")
        if template_file.blob is None:
            raise BadRequestException(
                "The selected DOCX template could not be read because the file content is missing. Upload the template again or choose another DOCX file.",
                code="flow_template_missing_content",
            )

        placeholders = self._inspect_docx_template(template_file)
        if flow.id is None:
            raise BadRequestException(
                "Flow id missing while promoting legacy DOCX template asset."
            )
        template_asset_repo = self._require_template_asset_repo()
        return await template_asset_repo.create(
            flow_id=flow.id,
            space_id=flow.space_id,
            tenant_id=self.user.tenant_id,
            file_id=template_file.id,
            name=template_file.name,
            checksum=template_file.checksum,
            mimetype=template_file.mimetype,
            placeholders=self._placeholder_names(placeholders),
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
            status="ready",
        )

    @staticmethod
    def _placeholder_names(placeholders: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for item in placeholders:
            name = str(item["name"])
            if name not in names:
                names.append(name)
        return names
