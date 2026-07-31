from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from eneo.assistants.assistant import Assistant, AssistantOrigin
from eneo.assistants.assistant_service import AssistantService
from eneo.assistants.assistant_update import (
    AssistantUpdateCaller,
    AssistantUpdateCommand,
)
from eneo.files.file_models import File
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowPersistedJsonObject,
    FlowSparse,
    FlowStep,
    FlowTemplateAsset,
)
from eneo.flows.domain.flow_invariant_exceptions import (
    FlowPublishedDefinitionInvalidError,
)
from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_metadata import (
    normalize_flow_metadata_for_write,
    normalize_persisted_flow_metadata,
)
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
)
from eneo.flows.flow_review_policy import dump_flow_step_review_policy
from eneo.flows.flow_security_classification import (
    evaluate_step_security_classification,
)
from eneo.flows.flow_template_asset_service import FlowTemplateAssetService
from eneo.flows.flow_validators import (
    validate_steps,
    validate_variable_alias_collisions,
)
from eneo.flows.http_transport import (
    AuthoredSecretEncryptionUnavailableError,
    HttpAuthoredConfig,
    contains_secret_sentinel,
    is_authored_config,
    merge_secrets_on_update,
    protect_authored_secrets,
    unprotected_persisted_secret_fields,
    unresolved_secret_sentinel_fields,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import (
    build_published_definition_json,
    parse_published_runtime_steps,
)
from eneo.flows.runtime.docx_template_runtime import (
    extract_docx_template_text_preview,
    inspect_docx_template_bytes,
)
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED, NotProvided, ResourcePermission
from eneo.settings.encryption_service import EncryptionService
from eneo.spaces.space_service import SpaceService
from eneo.users.user import UserInDB


class FlowService:
    """Tenant-scoped business service for flow lifecycle operations."""

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_version_repo: FlowVersionRepository,
        assistant_service: AssistantService,
        template_asset_service: FlowTemplateAssetService | None = None,
        encryption_service: EncryptionService | None = None,
        space_service: SpaceService | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_version_repo = flow_version_repo
        self.assistant_service = assistant_service
        self.template_asset_service = template_asset_service
        self.encryption_service = encryption_service
        self.space_service = space_service

    def _require_template_asset_service(self) -> FlowTemplateAssetService:
        if self.template_asset_service is None:
            raise RuntimeError(
                "FlowService requires template_asset_service for template asset operations."
            )
        return self.template_asset_service

    async def create_flow(
        self,
        *,
        space_id: UUID,
        name: str,
        steps: list[FlowStep],
        description: str | None = None,
        metadata_json: FlowPersistedJsonObject | None = None,
        data_retention_days: int | None = None,
        owner_user_id: UUID | None = None,
    ) -> Flow:
        normalized_metadata = normalize_flow_metadata_for_write(metadata_json)
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
        persisted_steps = self._protect_authored_step_secrets(normalized_steps)
        self._reject_unresolved_secret_sentinels(persisted_steps)
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

    async def replace_resource_bindings(
        self,
        *,
        flow_id: UUID,
        bindings: tuple[LocalResourceBinding, ...],
        source: FlowResourceBindingSource,
    ) -> None:
        await self.flow_repo.replace_resource_bindings(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
            bindings=bindings,
            source=source,
        )

    async def list_resource_bindings(
        self,
        *,
        flow_id: UUID,
    ) -> tuple[LocalResourceBinding, ...]:
        return await self.flow_repo.list_resource_bindings(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )

    async def update_flow(
        self,
        *,
        flow_id: UUID,
        name: str | NotProvided = NOT_PROVIDED,
        description: str | None | NotProvided = NOT_PROVIDED,
        steps: list[FlowStep] | None = None,
        metadata_json: FlowPersistedJsonObject | None | NotProvided = NOT_PROVIDED,
        data_retention_days: int | None | NotProvided = NOT_PROVIDED,
        expected_revision: int | None = None,
    ) -> Flow:
        existing = await self.get_flow(flow_id)
        if existing.published_version is not None:
            raise BadRequestException(
                "Cannot mutate a published flow. Unpublish first."
            )

        if steps is not None:
            self._validate_update_step_identity(
                incoming_steps=steps,
                stored_steps=existing.steps,
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

        next_metadata = normalize_persisted_flow_metadata(existing.metadata_json)
        if metadata_json is not NOT_PROVIDED:
            next_metadata = normalize_flow_metadata_for_write(
                cast(FlowPersistedJsonObject | None, metadata_json)
            )
        self._validate_steps(next_steps, metadata_json=next_metadata)
        self._validate_variable_alias_collisions(
            steps=next_steps,
            metadata_json=next_metadata,
        )

        next_retention = existing.data_retention_days
        if data_retention_days is not NOT_PROVIDED:
            next_retention = data_retention_days

        normalized_steps = self._normalize_steps_for_tenant(next_steps)
        if steps is not None:
            normalized_steps = self._protect_authored_step_secrets(normalized_steps)
        persisted_steps = self._merge_step_secrets(normalized_steps, existing.steps)
        self._reject_unresolved_secret_sentinels(persisted_steps)
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
    ) -> AssistantAuthoringSnapshots:
        assistant_ids = list(dict.fromkeys(step.assistant_id for step in flow.steps))
        return await self.flow_repo.get_assistant_snapshots(
            assistant_ids=assistant_ids,
            tenant_id=self.user.tenant_id,
        )

    async def count_flow_step_assistants_with_mcp_configuration(
        self,
        *,
        flow_id: UUID,
    ) -> int:
        return await self.flow_repo.count_flow_step_assistants_with_mcp_configuration(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )

    async def update_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
        update: AssistantUpdateCommand,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        if update.is_set("mcp_server_ids") or update.is_set("mcp_tools"):
            raise BadRequestException(
                "Flow MCP is unsupported. MCP servers and tools cannot be configured on a Flow assistant."
            )
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        await self._validate_flow_assistant_security_change(
            flow=flow,
            assistant=assistant,
            update=update,
        )
        return await self.assistant_service.update_assistant(
            assistant_id=assistant_id,
            update=update,
            caller=AssistantUpdateCaller.FLOW_MANAGED,
            include_hidden=True,
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
        return await self.flow_repo.update(
            updated,
            tenant_id=self.user.tenant_id,
            expected_revision=flow.draft_revision,
        )

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
        normalized_metadata = normalize_persisted_flow_metadata(flow.metadata_json)
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
        self._reject_unprotected_stored_secrets(flow.steps)

        latest = await self.flow_version_repo.get_latest(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        next_version = 1 if latest is None else latest.version + 1

        flow_with_normalized_metadata = flow.model_copy(
            update={"metadata_json": normalized_metadata},
            deep=True,
        )
        definition = await self._build_definition(flow_with_normalized_metadata)
        self._validate_published_definition_snapshot(
            definition,
            flow_id=flow_id,
            flow_version=next_version,
        )
        await self.flow_version_repo.create(
            flow_id=flow_id,
            version=next_version,
            definition_json=definition,
            tenant_id=self.user.tenant_id,
        )

        updated = flow_with_normalized_metadata.model_copy(
            update={
                "published_version": next_version,
            },
            deep=True,
        )
        return await self.flow_repo.update(
            updated,
            tenant_id=self.user.tenant_id,
            expected_revision=flow.draft_revision,
        )

    def _validate_publishable(
        self, flow: Flow, *, metadata_json: FlowPersistedJsonObject | None
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
        metadata_json: FlowPersistedJsonObject | None = None,
        require_complete_template_fill_config: bool = False,
    ) -> None:
        validate_steps(
            steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=require_complete_template_fill_config,
        )

    def _validate_variable_alias_collisions(
        self,
        *,
        steps: list[FlowStep],
        metadata_json: FlowPersistedJsonObject | None,
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
        update: AssistantUpdateCommand,
    ) -> None:
        if self.space_service is None:
            return

        if not update.changed_security_field_names():
            return

        if not any(step.assistant_id == assistant.id for step in flow.steps):
            return

        space = await self.space_service.get_space(flow.space_id)
        candidate_assistant = (
            self._build_candidate_flow_assistant_for_security_validation(
                assistant=assistant,
                space=space,
                update=update,
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
        update: AssistantUpdateCommand,
    ) -> Any:
        completion_model = assistant.completion_model
        if update.is_set("completion_model_id"):
            next_completion_model_id = update.completion_model_id
            completion_model = (
                space.get_completion_model(next_completion_model_id)
                if next_completion_model_id is not None
                else None
            )

        collections = assistant.collections
        if update.is_set("groups") and update.groups is not None:
            collections = [space.get_collection(group_id) for group_id in update.groups]

        websites = assistant.websites
        if update.is_set("websites") and update.websites is not None:
            websites = [space.get_website(website_id) for website_id in update.websites]

        integration_knowledge_list = assistant.integration_knowledge_list
        if update.is_set("integration_knowledge_ids") and (
            update.integration_knowledge_ids is not None
        ):
            integration_knowledge_list = [
                space.get_integration_knowledge(integration_knowledge_id)
                for integration_knowledge_id in update.integration_knowledge_ids
            ]

        return SimpleNamespace(
            completion_model=completion_model,
            collections=collections,
            websites=websites,
            integration_knowledge_list=integration_knowledge_list,
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

    def _protect_authored_step_secrets(self, steps: list[FlowStep]) -> list[FlowStep]:
        """Encrypt author-supplied HTTP credentials, or refuse to store them raw.

        Runs on incoming authored steps, before stored-secret sentinels are
        merged: only here is a secret value known to have come from the author
        rather than from the existing row. Encrypting at this point is what lets
        the merge combine ciphertext with ciphertext.
        """
        return [
            step.model_copy(
                update={
                    "input_config": self._protect_config(
                        step.input_config,
                        step_order=step.step_order,
                        label="input_config",
                    ),
                    "output_config": self._protect_config(
                        step.output_config,
                        step_order=step.step_order,
                        label="output_config",
                    ),
                },
                deep=True,
            )
            for step in steps
        ]

    def _protect_config(
        self,
        config: FlowPersistedJsonObject | None,
        *,
        step_order: int,
        label: str,
    ) -> FlowPersistedJsonObject | None:
        if config is None or not is_authored_config(config):
            return config
        authored = HttpAuthoredConfig.model_validate(config)
        try:
            protected = protect_authored_secrets(authored, self.encryption_service)
        except AuthoredSecretEncryptionUnavailableError as exc:
            raise FlowStepValidationError(
                f"Step {step_order}: {label} carries HTTP credentials "
                f"({', '.join(exc.secret_fields)}) that cannot be stored while "
                "credential encryption is inactive. Configure ENCRYPTION_KEY, or "
                "remove the credentials, before saving this step.",
                step_order=step_order,
            ) from exc
        return protected.model_dump(mode="json")

    def _reject_unprotected_stored_secrets(self, steps: list[FlowStep]) -> None:
        """Refuse to publish credentials that are not protected in storage.

        Publishing copies the stored config into an immutable version, so an
        unprotected credential would be duplicated into a second place it can
        leak from. The published definition is what the runtime decrypts, so
        the secret cannot simply be stripped here — the row has to be fixed.
        """
        for step in steps:
            for label, config in (
                ("input_config", step.input_config),
                ("output_config", step.output_config),
            ):
                unprotected = unprotected_persisted_secret_fields(
                    config,
                    self.encryption_service,
                )
                if unprotected:
                    raise FlowStepValidationError(
                        f"Step {step.step_order}: {label} stores HTTP credentials "
                        f"({', '.join(unprotected)}) whose protection cannot be "
                        "proved, so publishing would copy them into a published "
                        "version. Configure ENCRYPTION_KEY and re-enter the "
                        "credentials before publishing.",
                        step_order=step.step_order,
                    )

    def _reject_unresolved_secret_sentinels(self, steps: list[FlowStep]) -> None:
        """Refuse sentinels that resolved to no stored credential.

        A sentinel means "keep what is already stored". Once stored secrets have
        been merged, one that remains points at nothing, and persisting it would
        store the sentinel itself in place of the credential.
        """
        for step in steps:
            for label, config in (
                ("input_config", step.input_config),
                ("output_config", step.output_config),
            ):
                if config is None or not is_authored_config(config):
                    continue
                unresolved = unresolved_secret_sentinel_fields(
                    HttpAuthoredConfig.model_validate(config)
                )
                if unresolved:
                    raise FlowStepValidationError(
                        f"Step {step.step_order}: {label} keeps stored HTTP "
                        f"credentials ({', '.join(unresolved)}) that no longer "
                        "exist. Re-enter the credentials before saving this step.",
                        step_order=step.step_order,
                    )

    def _merge_step_secrets(
        self,
        incoming_steps: list[FlowStep],
        stored_steps: list[FlowStep],
    ) -> list[FlowStep]:
        """Merge secret sentinels by persisted draft step id, not mutable order."""
        stored_by_id = {step.id: step for step in stored_steps if step.id is not None}
        result: list[FlowStep] = []
        for step in incoming_steps:
            stored = stored_by_id.get(step.id) if step.id is not None else None
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

    def _validate_update_step_identity(
        self,
        *,
        incoming_steps: list[FlowStep],
        stored_steps: list[FlowStep],
    ) -> None:
        stored_ids = {step.id for step in stored_steps if step.id is not None}
        seen_ids: set[UUID] = set()
        seen_orders: set[int] = set()
        for step in incoming_steps:
            if step.step_order in seen_orders:
                raise BadRequestException(
                    "A step order can only appear once in a flow update.",
                    code="duplicate_step_order",
                )
            seen_orders.add(step.step_order)
            if step.id is None:
                if self._step_has_secret_sentinel(step):
                    raise BadRequestException(
                        "Secret sentinel values require an existing draft step id.",
                        code="sentinel_secret_requires_step_id",
                    )
                continue
            if step.id in seen_ids:
                raise BadRequestException(
                    "A draft step id can only appear once in a flow update.",
                    code="duplicate_step_id",
                )
            seen_ids.add(step.id)
            if step.id not in stored_ids:
                raise BadRequestException(
                    "Flow update references an unknown draft step id.",
                    code="unknown_step_id",
                )

    @classmethod
    def _step_has_secret_sentinel(cls, step: FlowStep) -> bool:
        return contains_secret_sentinel(step.input_config) or contains_secret_sentinel(
            step.output_config
        )

    @staticmethod
    def _merge_config_secrets(
        incoming: FlowPersistedJsonObject | None, stored: FlowPersistedJsonObject | None
    ) -> FlowPersistedJsonObject | None:
        if incoming is None or not is_authored_config(incoming):
            return incoming
        if stored is None or not is_authored_config(stored):
            return incoming
        incoming_config = HttpAuthoredConfig.model_validate(incoming)
        stored_config = HttpAuthoredConfig.model_validate(stored)
        merged = merge_secrets_on_update(incoming_config, stored_config)
        return merged.model_dump(mode="json")

    async def _build_definition(self, flow: Flow) -> FlowPersistedJsonObject:
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

    @staticmethod
    def _validate_published_definition_snapshot(
        definition_json: FlowPersistedJsonObject,
        *,
        flow_id: UUID,
        flow_version: int,
    ) -> None:
        try:
            parse_published_runtime_steps(
                definition_json,
                flow_version=flow_version,
            )
        except BadRequestException as exc:
            raise FlowPublishedDefinitionInvalidError(
                flow_id=flow_id,
                flow_version=flow_version,
                parser_message=str(exc),
                parser_code=exc.code,
                parser_context=dict(exc.context) if exc.context is not None else None,
            ) from exc

    async def _step_to_definition(
        self,
        step: FlowStep,
        *,
        flow: Flow,
    ) -> FlowPersistedJsonObject:
        output_config = step.output_config
        if step.output_mode == "template_fill":
            output_config = await self._prepare_template_output_config_for_publish(
                step,
                flow=flow,
            )
        assistant, _ = await self.assistant_service.get_assistant(step.assistant_id)
        if assistant.mcp_servers:
            raise BadRequestException(
                f"Step {step.step_order}: Flow MCP is unsupported. Remove MCP servers and tools from the step assistant before publishing."
            )
        assistant_snapshot = build_assistant_execution_snapshot(
            assistant=assistant,
        )
        return {
            "step_id": str(step.id) if step.id is not None else None,
            "step_order": step.step_order,
            "timeout_seconds": step.timeout_seconds,
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
            "assistant_snapshot": assistant_snapshot,
            "input_config": step.input_config,
            "output_config": output_config,
            "review_policy": dump_flow_step_review_policy(step.review_policy),
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
        for placeholder, binding in cast(FlowPersistedJsonObject, bindings).items():
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
        next_output_config["template_checksum"] = template_file.checksum
        next_output_config["template_name"] = template_file.name
        next_output_config["placeholders"] = placeholder_names
        return next_output_config

    async def _get_template_asset_file(
        self,
        *,
        flow_id: UUID | None,
        asset_id: UUID,
    ) -> tuple[FlowTemplateAsset, File]:
        if flow_id is None:
            raise RuntimeError(
                "A persisted Flow is required to resolve a template asset"
            )
        return await self._require_template_asset_service().get_asset_with_file(
            flow_id=flow_id,
            asset_id=asset_id,
        )

    async def _resolve_template_asset_reference(
        self,
        *,
        step: FlowStep,
        flow: Flow,
    ) -> tuple[FlowTemplateAsset, File]:
        if not isinstance(step.output_config, dict):
            raise BadRequestException(
                f"Step {step.step_order}: output_config must be an object for output_mode 'template_fill'."
            )
        flow_id = flow.require_persisted_id()

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
                    flow_id=flow_id,
                    asset_id=template_asset_id,
                )
            except NotFoundException as exc:
                raise self._template_not_accessible_error(
                    step_order=step.step_order
                ) from exc

        raise BadRequestException(
            f"Step {step.step_order}: output_config.template_asset_id must be configured."
        )

    def _inspect_docx_template(self, file: File) -> list[dict[str, Any]]:
        return inspect_docx_template_bytes(file.blob or b"", filename=file.name)

    @staticmethod
    def _template_not_accessible_error(*, step_order: int) -> BadRequestException:
        return BadRequestException(
            f"Step {step_order}: selected DOCX template is no longer available for this flow. Upload the template again or choose another DOCX file.",
            code=FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE.value,
        )

    @staticmethod
    def _placeholder_names(placeholders: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for item in placeholders:
            name = str(item["name"])
            if name not in names:
                names.append(name)
        return names
