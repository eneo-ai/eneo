from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from eneo.assistants.assistant import Assistant, AssistantOrigin
from eneo.assistants.assistant_service import AssistantService
from eneo.assistants.assistant_update import (
    AssistantUpdateCaller,
    AssistantUpdateCommand,
)
from eneo.files.file_models import File
from eneo.flows.application.flow_tool_options import (
    FlowToolOptions,
    SpaceToolOptions,
    read_flow_tool_options,
    read_space_tool_options,
)
from eneo.flows.application.flow_tool_publication import (
    pin_tool_steps,
    published_input_config,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
)
from eneo.flows.domain.canonical_json_hash import json_values_differ
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
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
    provider_backed_model_required,
    require_completion_model_for_step,
)
from eneo.flows.domain.step_config import clean_inactive_step_config
from eneo.flows.domain.tool_facts import (
    SpaceToolFactsSource,
    ToolFactsReadOnce,
    UnattendedToolFactsSource,
)
from eneo.flows.domain.tool_input import PublishedToolInputConfig
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_authoring_transcription import (
    fill_default_speaker_service,
    kept_speaker_service_id,
    lacks_speaker_service_choice,
    require_chosen_speaker_service,
    require_usable_speaker_service,
    transcription_config_for_write,
)
from eneo.flows.flow_metadata import (
    normalize_flow_metadata_for_write,
    normalize_persisted_flow_metadata,
)
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
)
from eneo.flows.flow_review_policy import dump_flow_step_review_policy
from eneo.flows.flow_runtime_policy import (
    resolve_flow_runtime_policy,
    resolve_step_timeout_seconds,
)
from eneo.flows.flow_security_classification import (
    FlowStepClassificationExplanation,
    explain_flow_security_classification,
    require_flow_security_classification,
)
from eneo.flows.flow_template_asset_service import FlowTemplateAssetService
from eneo.flows.flow_validators import (
    draft_step_refusals,
    publish_step_refusals,
    retained_contracts,
    validate_step_count,
    validate_steps,
    validate_variable_alias_collisions,
)
from eneo.flows.flow_validators_http import credential_template_error
from eneo.flows.flow_validators_template import validate_template_placeholder_bindings
from eneo.flows.http_transport import (
    AuthoredSecretEncryptionUnavailableError,
    HttpAuthoredConfig,
    contains_secret_sentinel,
    is_authored_config,
    merge_secrets_on_update,
    protect_authored_secrets,
    templated_step_credentials,
    unprotected_persisted_secret_fields,
    unresolved_secret_sentinel_fields,
)
from eneo.flows.infrastructure.flow_repo import (
    AssistantReclaimBlocker,
    DraftRevisionReservation,
    FlowRepository,
    StoredAssistantPrompt,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import (
    build_published_definition_json,
    parse_published_runtime_steps,
)
from eneo.flows.runtime.document_runtime_preflight import require_document_runtime
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED, NotProvided, ResourcePermission
from eneo.settings.encryption_service import EncryptionService
from eneo.spaces.space import Space
from eneo.spaces.space_service import SpaceService
from eneo.users.user import UserInDB


def published_draft_refusal(flow: Flow) -> BadRequestException | None:
    """The refusal of any change to the draft of a published flow."""
    if flow.published_version is None:
        return None
    return BadRequestException(
        "Cannot mutate a published flow. Unpublish first.",
        code=FlowApiErrorCode.UNPUBLISH_REQUIRED.value,
    )


def steps_as_written(
    steps: Sequence[FlowStep], *, unchanged_step_ids: frozenset[UUID] = frozenset()
) -> list[FlowStep]:
    """The steps a draft write stores: a saved step the caller hands back as
    saved (``unchanged_step_ids``) as given, every other one without the
    settings of the modes it does not use."""
    return [
        step
        if step.id is not None and step.id in unchanged_step_ids
        else clean_inactive_step_config(step)
        for step in steps
    ]


def draft_write_metadata(
    saved: FlowPersistedJsonObject | None,
    metadata_json: FlowPersistedJsonObject | None | NotProvided = NOT_PROVIDED,
) -> FlowPersistedJsonObject | None:
    """The metadata a draft write judges its steps against: the one it
    writes, else the saved one."""
    if metadata_json is NOT_PROVIDED:
        return normalize_persisted_flow_metadata(saved)
    return normalize_flow_metadata_for_write(
        cast(FlowPersistedJsonObject | None, metadata_json)
    )


@dataclass(frozen=True, slots=True)
class CandidateAssistantChange:
    """An unsaved change to a step assistant, with the meaning of an editor
    update's assistant change: to the assistant itself, or, with ``step_id``
    naming a step whose assistant other steps share, to that step's own copy
    of it."""

    assistant_id: UUID
    update: AssistantUpdateCommand
    step_id: UUID | None = None


def _assistant_delete_refusal(
    *, flow_id: UUID, assistant_id: UUID, blocker: AssistantReclaimBlocker
) -> BadRequestException:
    if blocker.reason == "unfinished_run_reference":
        message = (
            f"An unfinished run of version {blocker.version} still uses this "
            "assistant. Retry after it finishes."
        )
    else:
        message = (
            "A step of the flow still uses this assistant. Remove or replace "
            "that step first."
        )
    context: dict[str, Any] = {
        "flow_id": str(flow_id),
        "assistant_ids": [str(assistant_id)],
        "reason": blocker.reason,
    }
    if blocker.version is not None:
        context["flow_version"] = blocker.version
    return BadRequestException(
        message, code=FlowApiErrorCode.FLOW_MANAGED_ASSISTANT.value, context=context
    )


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
        tool_facts_reader: SpaceToolFactsSource | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_version_repo = flow_version_repo
        self.assistant_service = assistant_service
        self.template_asset_service = template_asset_service
        self.encryption_service = encryption_service
        self.space_service = space_service
        self.tool_facts_reader = tool_facts_reader

    def _require_tool_facts_reader(self) -> SpaceToolFactsSource:
        if self.tool_facts_reader is None:
            raise RuntimeError(
                "FlowService requires tool_facts_reader to read the MCP tool decision."
            )
        return self.tool_facts_reader

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
        description: str | None = None,
        metadata_json: FlowPersistedJsonObject | None = None,
        owner_user_id: UUID | None = None,
    ) -> Flow:
        """A new flow, with no steps: each step runs an assistant the flow
        owns (``create_flow_assistant``), so its steps are set by an update."""
        normalized_metadata, space = await self._fill_default_speaker_service(
            space_id=space_id,
            metadata_json=normalize_flow_metadata_for_write(metadata_json),
        )
        # A form field alone can take a name the run reserves.
        self._validate_variable_alias_collisions(
            steps=[], metadata_json=normalized_metadata
        )
        await self._check_speaker_service(
            space_id=space_id, metadata_json=normalized_metadata, space=space
        )
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
            created_at=None,
            updated_at=None,
            steps=[],
        )
        return await self.flow_repo.create(flow=flow, tenant_id=self.user.tenant_id)

    async def get_flow(self, flow_id: UUID) -> Flow:
        return await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)

    async def list_flows(
        self,
        *,
        space_ids: Collection[UUID],
        draft_space_ids: Collection[UUID],
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowSparse]:
        """Published flows in `space_ids` and drafts in `draft_space_ids`."""
        return await self.flow_repo.get_sparse_by_spaces(
            tenant_id=self.user.tenant_id,
            space_ids=space_ids,
            draft_space_ids=draft_space_ids,
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
        expected_revision: int | None = None,
        unchanged_step_ids: frozenset[UUID] = frozenset(),
        keep_saved_form_fields: bool = False,
    ) -> Flow:
        """`unchanged_step_ids`: saved steps the caller hands back as they are
        saved. They are written as given: dropping the configuration of modes
        they do not use would be a change nobody made.

        `keep_saved_form_fields`: a form field of `metadata_json` whose type
        reads as the saved field's of its name is stored with the type it was
        saved with (a legacy type such as `email` stays `email`), whatever
        else the edit changes on it; one that reads the same throughout is
        stored exactly as saved. Validation reads every field normalized
        either way."""

        existing = await self.get_flow(flow_id)
        refusal = published_draft_refusal(existing)
        if refusal is not None:
            raise refusal

        if steps is not None:
            validate_step_count(len(steps))
            steps = steps_as_written(steps, unchanged_step_ids=unchanged_step_ids)
            self._validate_update_step_identity(
                incoming_steps=steps,
                stored_steps=existing.steps,
            )
        next_steps = (
            steps
            if steps is not None
            else [clean_inactive_step_config(step) for step in existing.steps]
        )
        await self._validate_assistant_scope_for_steps(
            space_id=existing.space_id,
            steps=next_steps,
            owning_flow_id=existing.require_persisted_id(),
        )

        next_metadata = draft_write_metadata(existing.metadata_json, metadata_json)
        space: Space | None = None
        if steps is not None or metadata_json is not NOT_PROVIDED:
            # Any draft write stores the default as the choice of a flow that
            # has none, also when the write names no metadata.
            next_metadata, space = await self._fill_default_speaker_service(
                space_id=existing.space_id,
                metadata_json=next_metadata,
            )
        # A step's own defect is reported before the classification, which
        # reads its configuration (create and publish validate first too).
        refusals = draft_step_refusals(
            next_steps,
            metadata_json=next_metadata,
            retained=retained_contracts(next_steps, existing.steps),
        )
        if refusals:
            raise refusals[0]
        self._refuse_step_timeouts_above_the_maximum(next_steps)
        # An edit that leaves the metadata alone states no new choice.
        if metadata_json is not NOT_PROVIDED:
            space = await self._check_speaker_service(
                space_id=existing.space_id,
                metadata_json=next_metadata,
                kept_metadata_json=existing.metadata_json,
                space=space,
            )
        await self._validate_step_security_classification_for_steps(
            space_id=existing.space_id,
            steps=next_steps,
            space=space,
        )

        normalized_steps = self._normalize_steps_for_tenant(next_steps)
        if steps is not None:
            normalized_steps = self._protect_authored_step_secrets(
                normalized_steps,
                stored_steps=existing.steps,
                unchanged_step_ids=unchanged_step_ids,
            )
        persisted_steps = self._merge_step_secrets(
            normalized_steps, existing.steps, unchanged_step_ids=unchanged_step_ids
        )
        self._reject_unresolved_secret_sentinels(persisted_steps)
        # The step validation saw a retained credential as a sentinel; it is
        # read here, once the stored value is back.
        self._reject_templated_stored_secrets(persisted_steps)
        updated = existing.model_copy(
            deep=True,
            update={
                "name": existing.name if name is NOT_PROVIDED else name,
                "description": (
                    existing.description if description is NOT_PROVIDED else description
                ),
                "steps": persisted_steps,
                "metadata_json": (
                    _with_saved_form_fields(next_metadata, existing.metadata_json)
                    if keep_saved_form_fields
                    else next_metadata
                ),
            },
        )
        persisted = await self.flow_repo.update(
            flow=updated,
            tenant_id=self.user.tenant_id,
            expected_revision=expected_revision,
        )
        # A flow-managed assistant goes with its last step. Flow edit access
        # authorizes the deletion: the flow owns the assistant.
        unreferenced_ids = {step.assistant_id for step in existing.steps} - {
            step.assistant_id for step in persisted_steps
        }
        if unreferenced_ids:
            await self.assistant_service.delete_flow_managed_assistants(
                flow_id=flow_id,
                assistant_ids=await self.flow_repo.orphaned_flow_managed_assistant_ids(
                    flow_id=flow_id,
                    tenant_id=self.user.tenant_id,
                    assistant_ids=unreferenced_ids,
                ),
            )
        return persisted

    async def lock_live_flow(self, flow_id: UUID) -> None:
        """Take the flow row lock that delete, publish and run creation take,
        held until the transaction ends. Raises NotFound when the flow is
        deleted, so a write made under it cannot reference a deleted flow."""
        await self.flow_repo.lock_publication_pointer(
            flow_id=flow_id, tenant_id=self.user.tenant_id
        )

    async def delete_flow(self, flow_id: UUID) -> None:
        await self.assistant_service.delete_flow_managed_assistants(
            flow_id=flow_id,
            assistant_ids=await self.flow_repo.delete(
                flow_id=flow_id, tenant_id=self.user.tenant_id
            ),
        )

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
        assistant, permissions = await self.assistant_service.get_assistant(
            assistant_id
        )
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return assistant, permissions

    async def get_flow_assistant_prompts(
        self, flow: Flow
    ) -> dict[UUID, StoredAssistantPrompt]:
        """The prompt each of the flow's assistants has selected, as stored."""

        return await self.flow_repo.get_selected_prompts(
            assistant_ids=list(dict.fromkeys(step.assistant_id for step in flow.steps)),
            tenant_id=self.user.tenant_id,
        )

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

    async def reserve_draft_revision(
        self, *, flow_id: UUID, expected_revision: int | None
    ) -> DraftRevisionReservation:
        """The flow's draft locked for this transaction's writes, fenced on
        `expected_revision` or, when omitted, on the revision read now (the
        rule of `update_flow`). Taken before writing any of its assistants."""

        if expected_revision is None:
            expected_revision = (await self.get_flow(flow_id)).draft_revision
        return await self.flow_repo.reserve_draft_revision(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
            expected_revision=expected_revision,
        )

    async def update_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
        update: AssistantUpdateCommand,
        expected_revision: int | None = None,
    ) -> tuple[Assistant, list[ResourcePermission], int]:
        """A flow-managed assistant is part of its flow's draft, so writing it
        advances the draft revision once, fenced like a flow update. Returns
        the assistant, its permissions and the draft's new revision."""

        reservation = await self.reserve_draft_revision(
            flow_id=flow_id, expected_revision=expected_revision
        )
        assistant, permissions = await self.update_reserved_flow_assistant(
            reservation=reservation, assistant_id=assistant_id, update=update
        )
        return (
            assistant,
            permissions,
            await self.flow_repo.advance_draft_revision(reservation),
        )

    async def update_reserved_flow_assistant(
        self,
        *,
        reservation: DraftRevisionReservation,
        assistant_id: UUID,
        update: AssistantUpdateCommand,
        classification_judged_by_flow_update: bool = False,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Write an assistant of the reserved draft. The revision is advanced
        by the caller: once per write (`update_flow_assistant`), or once for
        the whole apply by its `update_flow`.

        `classification_judged_by_flow_update`: the caller saves the flow's
        steps with `update_flow` later in the same transaction, and that judges
        every step's classification with its assistant as then saved. Judging
        this assistant alone now would read a prompt written for the new step
        positions against the steps as they are before the update."""

        if update.is_set("mcp_server_ids") or update.is_set("mcp_tools"):
            raise BadRequestException(
                "Flow MCP is unsupported. MCP servers and tools cannot be configured on a Flow assistant."
            )
        # Flows fill their own step templates and never read this choice.
        if update.is_set("document_template"):
            raise BadRequestException(
                "A document template cannot be chosen on a Flow assistant."
            )
        flow = await self.get_flow(reservation.flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        if not classification_judged_by_flow_update:
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

    async def copy_reserved_flow_assistant(
        self,
        *,
        reservation: DraftRevisionReservation,
        assistant_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """A copy of an assistant of the reserved draft, with its settings as
        they are, for a step that stops sharing it with other steps. The
        caller points the step at the copy in the same transaction."""

        flow = await self.get_flow(reservation.flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return await self.assistant_service.copy_flow_managed_assistant(
            assistant_id=assistant_id
        )

    async def delete_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
    ) -> None:
        flow = await self.get_flow(flow_id)
        # The flow lock every flow mutation takes (an edit, a publish, a run
        # start), held to the end of this transaction: nothing can attach,
        # publish or run the assistant between the checks and the delete. The
        # pointer read under it, not the read above, decides.
        if (
            await self.flow_repo.lock_publication_pointer(
                flow_id=flow_id, tenant_id=self.user.tenant_id
            )
            is not None
        ):
            raise BadRequestException(
                "Cannot mutate assistant of a published flow",
                code=FlowApiErrorCode.UNPUBLISH_REQUIRED.value,
            )
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        reclaimable = await self.flow_repo.orphaned_flow_managed_assistant_ids(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
            assistant_ids={assistant_id},
        )
        if assistant_id not in reclaimable:
            # No blocker left means the published version alone holds it,
            # which a mutable (unpublished) flow's draft cannot leave behind.
            blocker = await self.flow_repo.assistant_reclaim_blocker(
                flow_id=flow_id,
                tenant_id=self.user.tenant_id,
                assistant_id=assistant_id,
            )
            if blocker is not None:
                raise _assistant_delete_refusal(
                    flow_id=flow_id, assistant_id=assistant_id, blocker=blocker
                )
        try:
            await self.assistant_service.delete_flow_managed_assistants(
                flow_id=flow_id, assistant_ids={assistant_id}
            )
        except BadRequestException as exc:
            # A step attached since the check above.
            if exc.code != FlowApiErrorCode.FLOW_MANAGED_ASSISTANT.value:
                raise
            raise _assistant_delete_refusal(
                flow_id=flow_id,
                assistant_id=assistant_id,
                blocker=AssistantReclaimBlocker(reason="step_reference"),
            ) from exc

    async def unpublish_flow(self, *, flow_id: UUID) -> Flow:
        flow = await self.get_flow(flow_id)
        if flow.published_version is None:
            raise BadRequestException(
                "Flow is not published.", code=FlowApiErrorCode.FLOW_NOT_PUBLISHED.value
            )
        updated = flow.model_copy(update={"published_version": None}, deep=True)
        return await self.flow_repo.update(
            updated,
            tenant_id=self.user.tenant_id,
            expected_revision=flow.draft_revision,
        )

    async def publish_flow(self, *, flow_id: UUID) -> Flow:
        flow = await self.get_flow(flow_id)
        await require_document_runtime(flow.steps)
        normalized_metadata = normalize_persisted_flow_metadata(flow.metadata_json)
        # The graph check reads each assistant's prompt (an input channel), so
        # the assistants load first, once the scope check has cleared them.
        await self._validate_assistant_scope_for_steps(
            space_id=flow.space_id,
            steps=flow.steps,
            owning_flow_id=flow.require_persisted_id(),
        )
        assistants_by_id = await self._load_step_assistants(flow.steps)
        self._validate_publishable(
            flow,
            metadata_json=normalized_metadata,
            prompt_templates={
                step.step_order: assistants_by_id[step.assistant_id].get_prompt_text()
                for step in flow.steps
            },
        )
        space = await self._check_speaker_service(
            space_id=flow.space_id,
            metadata_json=normalized_metadata,
            publishing_steps=flow.steps,
        )
        # One read of each tool's facts serves this publish: the classification
        # rule and the decision then judge the same rows.
        tool_facts = ToolFactsReadOnce(self._require_tool_facts_reader)
        await self._validate_step_security_classification_for_steps(
            space_id=flow.space_id,
            steps=flow.steps,
            assistants_by_id=assistants_by_id,
            space=space,
            tool_facts_reader=lambda: tool_facts,
        )
        self._reject_templated_stored_secrets(flow.steps)
        self._reject_unprotected_stored_secrets(flow.steps)

        flow_with_normalized_metadata = flow.model_copy(
            update={"metadata_json": normalized_metadata},
            deep=True,
        )
        tool_pins = await pin_tool_steps(
            flow.steps,
            facts_reader=lambda: tool_facts,
            tenant_id=self.user.tenant_id,
            space_id=flow.space_id,
        )
        # The version snapshots the assistants validated above, not a re-read.
        definition = await self._build_definition(
            flow_with_normalized_metadata,
            assistants_by_id=assistants_by_id,
            tool_pins=tool_pins,
        )

        # Lock after reading the draft so a concurrent publisher retains its
        # stale revision and gets the revision conflict when updating the pointer.
        await self.flow_repo.lock_publication_pointer(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        next_version = await self.flow_repo.allocate_next_version(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
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
            first_published_at=datetime.now(timezone.utc),
            source_draft_revision=flow.draft_revision,
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
        self,
        flow: Flow,
        *,
        metadata_json: FlowPersistedJsonObject | None,
        prompt_templates: Mapping[int, str],
    ) -> None:
        # The rules a suggestion's patch is checked against before it is
        # offered (flow_suggestion_service), so the two cannot drift.
        refusals = publish_step_refusals(
            flow.steps,
            metadata_json=metadata_json,
            prompt_templates=prompt_templates,
        )
        if refusals:
            raise refusals[0]
        # The maximum may have been lowered since the draft was saved.
        self._refuse_step_timeouts_above_the_maximum(flow.steps)

    def _refuse_step_timeouts_above_the_maximum(
        self, steps: Sequence[FlowStep]
    ) -> None:
        """A step may not ask for more time than the organisation allows: the
        run refuses it the same way (resolve_step_timeout_seconds)."""
        policy = resolve_flow_runtime_policy(self.user.tenant.flow_settings)
        for step in steps:
            resolve_step_timeout_seconds(
                step_order=step.step_order,
                step_timeout_seconds=step.timeout_seconds,
                policy=policy,
            )

    def _validate_steps(
        self,
        steps: list[FlowStep],
        *,
        metadata_json: FlowPersistedJsonObject | None = None,
        require_complete_template_fill_config: bool = False,
        prompt_templates: Mapping[int, str] | None = None,
        retained: frozenset[tuple[int, str]] = frozenset(),
    ) -> None:
        validate_steps(
            steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=require_complete_template_fill_config,
            prompt_templates=prompt_templates,
            retained=retained,
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
        owning_flow_id: UUID,
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

    async def _fill_default_speaker_service(
        self,
        *,
        space_id: UUID,
        metadata_json: FlowPersistedJsonObject | None,
    ) -> tuple[FlowPersistedJsonObject | None, Space | None]:
        """The metadata a draft write stores, with the organisation's default
        transcription service as the flow's choice when it transcribes and
        its author has made no choice (see ``fill_default_speaker_service``).
        Only draft writes call this; publishing never does.

        Also returns the space when it was loaded, for the checks that follow."""
        if self.space_service is None or not lacks_speaker_service_choice(
            metadata_json
        ):
            return metadata_json, None
        space = await self.space_service.get_space(space_id)
        return (
            fill_default_speaker_service(metadata=metadata_json, space=space),
            space,
        )

    async def _check_speaker_service(
        self,
        *,
        space_id: UUID,
        metadata_json: FlowPersistedJsonObject | None,
        kept_metadata_json: FlowPersistedJsonObject | None = None,
        publishing_steps: list[FlowStep] | None = None,
        space: Space | None = None,
    ) -> Space | None:
        """Refuse a malformed transcription choice, a chosen service the space
        may not use (whether or not the flow labels speakers: the service
        times the words too), and on publish (``publishing_steps``) a flow
        that asks for speaker labels without having chosen a service. A draft
        may be saved before the choice is made. A saved draft keeps the
        choice it has, as a space keeps its grants, so an administrator's
        later change never blocks unrelated edits; publishing checks it again.

        Returns the space (``space`` when the caller already loaded it) for
        the checks that follow, or None when none was needed."""
        config = transcription_config_for_write(metadata_json)
        pick = config.service_in_use
        if pick is not None and pick == kept_speaker_service_id(kept_metadata_json):
            pick = None
        if self.space_service is None or (pick is None and publishing_steps is None):
            return space
        if space is None:
            space = await self.space_service.get_space(space_id)
        if pick is not None:
            require_usable_speaker_service(pick, space=space)
        if publishing_steps is not None:
            require_chosen_speaker_service(config, steps=publishing_steps, space=space)
        return space

    async def _validate_step_security_classification_for_steps(
        self,
        *,
        space_id: UUID,
        steps: list[FlowStep],
        assistants_by_id: dict[UUID, Assistant] | None = None,
        space: Space | None = None,
        tool_facts_reader: Callable[[], UnattendedToolFactsSource] | None = None,
    ) -> None:
        """Refuse steps the classification rule refuses. ``tool_facts_reader``
        is the caller's when it asks about the same tools again (a publish);
        otherwise the service's own reader is used."""
        if self.space_service is None or not steps:
            return

        if space is None:
            space = await self.space_service.get_space(space_id)
        await require_flow_security_classification(
            steps=steps,
            assistants_by_id=(
                assistants_by_id
                if assistants_by_id is not None
                else await self._load_step_assistants(steps)
            ),
            space=space,
            security_enabled=self.user.tenant.security_enabled,
            tool_facts_reader=tool_facts_reader or self._require_tool_facts_reader,
            tenant_id=self.user.tenant_id,
            space_id=space_id,
        )

    async def preview_step_security_classification(
        self,
        *,
        flow_id: UUID,
        steps: list[FlowStep] | None = None,
        assistant_changes: Sequence[CandidateAssistantChange] = (),
    ) -> list[FlowStepClassificationExplanation]:
        """Explain the classification of the editor's unsaved state; writes nothing.

        The candidate steps replace the saved ones and each assistant change is
        applied to an in-memory copy of its assistant, as the editor update
        applies it: in order to the assistant itself, except a change naming a
        step whose assistant other candidate steps share, which gives that step
        its own copy, made from the assistant as the other changes left it.
        Then the save's own rule runs over the result. Only reads reach the
        repositories.
        """
        if self.space_service is None:
            raise RuntimeError("FlowService requires space_service to preview.")
        flow = await self.get_flow(flow_id)
        source_steps = steps if steps is not None else flow.steps
        validate_step_count(len(source_steps))
        candidate_steps = [clean_inactive_step_config(step) for step in source_steps]
        await self._validate_assistant_scope_for_steps(
            space_id=flow.space_id,
            steps=candidate_steps,
            owning_flow_id=flow.require_persisted_id(),
        )
        space = await self.space_service.get_space(flow.space_id)
        assistants_by_id: dict[UUID, Any] = dict(
            await self._load_step_assistants(candidate_steps)
        )
        if not {change.assistant_id for change in assistant_changes} <= (
            assistants_by_id.keys()
        ):
            raise BadRequestException(
                "Assistant changes must belong to assistants that steps of the flow use."
            )
        copies = _candidate_copies(assistant_changes, candidate_steps)
        for change in assistant_changes:
            if any(change is copy for copy in copies):
                continue
            assistants_by_id[change.assistant_id] = (
                self._build_candidate_flow_assistant_for_security_validation(
                    assistant=assistants_by_id[change.assistant_id],
                    space=space,
                    update=change.update,
                )
            )
        for change in copies:
            # An id only this preview knows, for the step's own copy.
            copy_id = uuid4()
            assistants_by_id[copy_id] = (
                self._build_candidate_flow_assistant_for_security_validation(
                    assistant=assistants_by_id[change.assistant_id],
                    space=space,
                    update=change.update,
                )
            )
            candidate_steps = [
                step.model_copy(update={"assistant_id": copy_id})
                if step.id == change.step_id
                else step
                for step in candidate_steps
            ]
        # The save's step refusal comes first, as in the save: the
        # classification reads the configuration a defective step holds.
        refusals = draft_step_refusals(
            candidate_steps,
            metadata_json=draft_write_metadata(flow.metadata_json),
            retained=retained_contracts(candidate_steps, flow.steps),
        )
        if refusals:
            raise refusals[0]
        return await explain_flow_security_classification(
            steps=candidate_steps,
            assistants_by_id=assistants_by_id,
            space=space,
            security_enabled=self.user.tenant.security_enabled,
            tool_facts_reader=self._require_tool_facts_reader,
            tenant_id=self.user.tenant_id,
            space_id=flow.space_id,
        )

    async def list_space_tool_options(self, *, space_id: UUID) -> SpaceToolOptions:
        """The tools of the general servers ``space_id`` has activated, each
        with what the decision says about it now, or that they exceed the
        list's bounds (``read_space_tool_options``); writes nothing. The
        caller has decided that the user may edit flows in the space."""
        return await read_space_tool_options(
            self._require_tool_facts_reader(),
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            security_enabled=self.user.tenant.security_enabled,
        )

    async def list_tool_options(self, *, flow_id: UUID) -> FlowToolOptions:
        """The tools of the general servers the flow's space has activated, in
        the reader's order, each with what the decision says about it now;
        writes nothing. Refused when they exceed the list's bounds
        (``read_flow_tool_options``)."""
        flow = await self.get_flow(flow_id)
        return await read_flow_tool_options(
            self._require_tool_facts_reader(),
            tenant_id=self.user.tenant_id,
            space_id=flow.space_id,
            security_enabled=self.user.tenant.security_enabled,
        )

    async def _load_step_assistants(
        self, steps: list[FlowStep]
    ) -> dict[UUID, Assistant]:
        assistants_by_id: dict[UUID, Assistant] = {}
        for step in sorted(steps, key=lambda item: item.step_order):
            if step.assistant_id in assistants_by_id:
                continue
            assistant, _ = await self.assistant_service.get_assistant(step.assistant_id)
            assistants_by_id[step.assistant_id] = assistant
        return assistants_by_id

    async def _validate_flow_assistant_security_change(
        self,
        *,
        flow: Flow,
        assistant: Assistant,
        update: AssistantUpdateCommand,
    ) -> None:
        if self.space_service is None:
            return

        # The prompt is an input channel (it interpolates prior outputs), so a
        # prompt-only edit can change which classified outputs the model reads.
        if not update.changed_security_field_names() and not update.is_set("prompt"):
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

        await require_flow_security_classification(
            steps=flow.steps,
            assistants_by_id=assistants_by_id,
            space=space,
            security_enabled=self.user.tenant.security_enabled,
            tool_facts_reader=self._require_tool_facts_reader,
            tenant_id=self.user.tenant_id,
            space_id=flow.space_id,
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

        # Mirror Assistant.update: a null prompt keeps the stored prompt; an
        # explicit PromptCreate (even empty text) replaces it.
        prompt_text = (
            update.prompt.text
            if update.is_set("prompt") and update.prompt is not None
            else assistant.get_prompt_text()
        )

        return SimpleNamespace(
            completion_model=completion_model,
            collections=collections,
            websites=websites,
            integration_knowledge_list=integration_knowledge_list,
            get_prompt_text=lambda: prompt_text,
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

    def _protect_authored_step_secrets(
        self,
        steps: list[FlowStep],
        *,
        stored_steps: Sequence[FlowStep] = (),
        unchanged_step_ids: frozenset[UUID] = frozenset(),
    ) -> list[FlowStep]:
        """Encrypt author-supplied HTTP credentials, or refuse to store them raw.

        Runs on incoming authored steps, before stored-secret sentinels are
        merged: only here is a secret value known to have come from the author
        rather than from the existing row. Encrypting at this point is what lets
        the merge combine ciphertext with ciphertext.

        What is not authored is left as it is: a step the caller hands back as
        saved (`unchanged_step_ids`), and a config equal to the one its saved
        step holds, carry what storage already protected.
        """
        stored_by_id = {step.id: step for step in stored_steps if step.id is not None}
        protected: list[FlowStep] = []
        for step in steps:
            stored = stored_by_id.get(step.id) if step.id is not None else None
            if stored is not None and step.id in unchanged_step_ids:
                protected.append(step)
                continue
            update: dict[str, object] = {}
            for label in ("input_config", "output_config"):
                config = getattr(step, label)
                if stored is not None and not json_values_differ(
                    config, getattr(stored, label)
                ):
                    continue
                update[label] = self._protect_config(
                    config, step_order=step.step_order, label=label
                )
            protected.append(step.model_copy(update=update, deep=True))
        return protected

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

    def _reject_templated_stored_secrets(self, steps: list[FlowStep]) -> None:
        """Refuse to save or publish a stored credential that holds a template.

        A credential is a literal; the runtime refuses to interpolate one. The
        stored value is ciphertext, so it is read as the runtime reads it.
        """
        for step in steps:
            for label, fields in templated_step_credentials(
                step_order=step.step_order,
                input_source=step.input_source,
                output_mode=step.output_mode,
                input_config=step.input_config,
                output_config=step.output_config,
                encryption_service=self.encryption_service,
            ):
                raise credential_template_error(
                    step_order=step.step_order, label=label, fields=fields
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
                        f"credentials ({', '.join(unresolved)}) that are unavailable "
                        "for this destination. Re-enter the credentials before saving this step.",
                        step_order=step.step_order,
                    )

    def _merge_step_secrets(
        self,
        incoming_steps: list[FlowStep],
        stored_steps: list[FlowStep],
        *,
        unchanged_step_ids: frozenset[UUID] = frozenset(),
    ) -> list[FlowStep]:
        """Merge secret sentinels by persisted draft step id, not mutable order.

        A step handed back as saved, and a config equal to the saved one, hold
        no sentinel to resolve: they are kept as they are, not re-shaped."""
        stored_by_id = {step.id: step for step in stored_steps if step.id is not None}
        result: list[FlowStep] = []
        for step in incoming_steps:
            stored = stored_by_id.get(step.id) if step.id is not None else None
            if stored is not None and step.id in unchanged_step_ids:
                result.append(step)
                continue
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
                    code=FlowGraphIssueCode.DUPLICATE_STEP_ORDER.value,
                )
            seen_orders.add(step.step_order)
            if step.id is None:
                if self._step_has_secret_sentinel(step):
                    raise FlowBadRequestException(
                        "Secret sentinel values require an existing draft step id.",
                        code=FlowApiErrorCode.SENTINEL_SECRET_REQUIRES_STEP_ID,
                    )
                continue
            if step.id in seen_ids:
                raise FlowBadRequestException(
                    "A draft step id can only appear once in a flow update.",
                    code=FlowApiErrorCode.DUPLICATE_STEP_ID,
                )
            seen_ids.add(step.id)
            if step.id not in stored_ids:
                raise FlowBadRequestException(
                    "Flow update references an unknown draft step id.",
                    code=FlowApiErrorCode.UNKNOWN_STEP_ID,
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
        if not json_values_differ(incoming, stored):
            return incoming
        incoming_config = HttpAuthoredConfig.model_validate(incoming)
        stored_config = HttpAuthoredConfig.model_validate(stored)
        merged = merge_secrets_on_update(incoming_config, stored_config)
        return merged.model_dump(mode="json")

    async def _build_definition(
        self,
        flow: Flow,
        *,
        assistants_by_id: dict[UUID, Assistant],
        tool_pins: Mapping[int, PublishedToolInputConfig],
    ) -> FlowPersistedJsonObject:
        return build_published_definition_json(
            flow_id=flow.require_persisted_id(),
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[
                await self._step_to_definition(
                    step,
                    flow=flow,
                    assistant=assistants_by_id[step.assistant_id],
                    tool_pin=tool_pins.get(step.step_order),
                )
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
        assistant: Assistant,
        tool_pin: PublishedToolInputConfig | None,
    ) -> FlowPersistedJsonObject:
        output_config = step.output_config
        if step.output_mode == "template_fill":
            output_config = await self._prepare_template_output_config_for_publish(
                step,
                flow=flow,
            )
        if assistant.mcp_servers:
            raise BadRequestException(
                f"Step {step.step_order}: Flow MCP is unsupported. Remove MCP servers and tools from the step assistant before publishing."
            )
        model = assistant.completion_model
        if model is not None and (model.provider_id is None or not model.provider_type):
            raise provider_backed_model_required(step.step_order)
        require_completion_model_for_step(
            step_order=step.step_order,
            output_mode=step.output_mode,
            has_completion_model=model is not None,
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
            "input_config": published_input_config(step, tool_pin),
            "output_config": output_config,
            "review_policy": dump_flow_step_review_policy(step.review_policy),
        }

    def _ensure_flow_is_mutable(self, flow: Flow) -> None:
        if flow.published_version is not None:
            raise BadRequestException(
                "Cannot mutate assistant of a published flow",
                code=FlowApiErrorCode.UNPUBLISH_REQUIRED.value,
            )

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

        (
            template_asset,
            template_file,
            names,
        ) = await self._resolve_template_asset_reference(
            step=step,
            flow=flow,
        )
        placeholder_names = list(names)
        validate_template_placeholder_bindings(
            step_order=step.step_order,
            placeholder_names=placeholder_names,
            bindings=step.output_config.get("bindings"),
        )

        next_output_config = dict(step.output_config)
        next_output_config["template_asset_id"] = str(template_asset.id)
        next_output_config["template_checksum"] = template_file.checksum
        next_output_config["template_name"] = template_file.name
        next_output_config["placeholders"] = placeholder_names
        return next_output_config

    async def _resolve_template_asset_reference(
        self,
        *,
        step: FlowStep,
        flow: Flow,
    ) -> tuple[FlowTemplateAsset, File, tuple[str, ...]]:
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
                return await self._require_template_asset_service().get_asset_for_publication(
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

    @staticmethod
    def _template_not_accessible_error(*, step_order: int) -> BadRequestException:
        return BadRequestException(
            f"Step {step_order}: selected DOCX template is no longer available for this flow. Upload the template again or choose another DOCX file.",
            code=FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE.value,
        )


def _candidate_copies(
    changes: Sequence[CandidateAssistantChange], steps: Sequence[FlowStep]
) -> list[CandidateAssistantChange]:
    """The changes that give their step its own copy of the assistant other
    ``steps`` share, as an editor update gives it. A change naming a step that
    is not among ``steps`` or does not use the assistant is refused."""

    copies: list[CandidateAssistantChange] = []
    for change in changes:
        if change.step_id is None:
            continue
        step = next((step for step in steps if step.id == change.step_id), None)
        if step is None or step.assistant_id != change.assistant_id:
            raise BadRequestException(
                "An assistant change names a step that does not use its assistant."
            )
        if any(
            other.id != step.id and other.assistant_id == step.assistant_id
            for other in steps
        ):
            copies.append(change)
    return copies


def _with_saved_form_fields(
    written: FlowPersistedJsonObject | None,
    saved: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject | None:
    """`written` with the saved field of each name as it is stored where the
    written field reads the same, and where only the label, requiredness,
    options or place differ, with the type the saved field is stored with: a
    type is replaced only when the edit changes what the platform reads."""

    written_schema = _form_schema(written)
    saved_schema = _form_schema(saved)
    saved_reads = _form_schema(normalize_persisted_flow_metadata(saved))
    if written is None or written_schema is None or saved_schema is None:
        return written
    if saved_reads is None:
        return written
    # The persisted read keeps every object field of the saved form, in order,
    # and normalizes each; a field that is not an object is dropped by both.
    stored = [
        cast(FlowPersistedJsonObject, field)
        for field in cast(list[object], saved_schema["fields"])
        if isinstance(field, dict)
    ]
    saved_by_name = {
        read["name"]: (read, field)
        for read, field in zip(
            cast(list[FlowPersistedJsonObject], saved_reads["fields"]),
            stored,
            strict=True,
        )
    }
    fields: list[FlowPersistedJsonObject] = []
    for field in cast(list[FlowPersistedJsonObject], written_schema["fields"]):
        read, stored_field = saved_by_name.get(field.get("name"), (None, None))
        if read is None or stored_field is None:
            fields.append(field)
        elif not json_values_differ(read, field):
            fields.append(stored_field)
        elif read.get("type") == field.get("type"):
            # A label, a requiredness or a place was edited, not the type.
            fields.append({**field, "type": stored_field.get("type")})
        else:
            fields.append(field)
    return {**written, "form_schema": {**written_schema, "fields": fields}}


def _form_schema(
    metadata: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject | None:
    if metadata is None:
        return None
    schema: object = metadata.get("form_schema")
    if not isinstance(schema, dict):
        return None
    form_schema = cast(FlowPersistedJsonObject, schema)
    return form_schema if isinstance(form_schema.get("fields"), list) else None
