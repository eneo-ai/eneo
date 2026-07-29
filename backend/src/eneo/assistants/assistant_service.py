import re
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Optional, TypeVar, Union, cast
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ModelKwargs,
    ResponseType,
    TokenUsage,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.assistants.assistant import Assistant
from eneo.assistants.assistant_factory import AssistantFactory
from eneo.assistants.assistant_repo import (
    AssistantRepository,
    PersonalDefaultValidationInput,
)
from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from eneo.authentication.auth_models import ApiKeyScopeType, ApiKeyStateReasonCode
from eneo.completion_models.infrastructure.context_builder import (
    count_tokens,
)
from eneo.completion_models.infrastructure.web_search import WebSearch
from eneo.files.attachment_budget import (
    assert_prompt_and_files_fit_context,
    attachment_token_ceiling,
)
from eneo.files.file_models import File, FileType
from eneo.files.file_service import FileService
from eneo.governance_policy.domain.policy_resolver import (
    select_effective_completion_model,
)
from eneo.help_assistants.application.ask_guard import assert_not_helper_assistant
from eneo.help_assistants.infrastructure.help_assistant_assignment_history_repo import (  # noqa: E501
    HelpAssistantAssignmentHistoryRepo,
)
from eneo.help_assistants.infrastructure.org_space_assistant_role_repo import (
    OrgSpaceAssistantRoleRepo,
)
from eneo.icons.icon_repo import IconRepository
from eneo.logging.logging import LoggingDetails
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.main.models import (
    NOT_PROVIDED,
    NotProvided,
    ResourcePermission,
    is_provided,
)
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.prompts.prompt import Prompt
from eneo.prompts.prompt_service import PromptService
from eneo.questions.question import ToolAssistant, ToolCallInfo, UseTools
from eneo.roles.permissions import (
    Permission,
    validate_permission,
    validate_permissions,
)
from eneo.services.service import DatastoreResult
from eneo.services.service_repo import ServiceRepository
from eneo.skills.domain.skill import (
    AssistantPinAdvanceIncompatibleReason,
    AssistantSkillConfigurationProjection,
    AssistantSkillRuntimeProjection,
    PersonalChatPinOverride,
    ResolvedSkillBinding,
    SkillActivationEvidenceV1,
    SkillActivationFallbackReason,
    SkillActivationMode,
    SkillActivationRejectionReason,
    SkillActivationUnavailableException,
    SkillBindingIntent,
    SkillComposition,
    SkillExecutionReference,
    SkillRuntimePolicy,
    SkillRuntimeResolution,
    SkillTurnEffectiveMode,
    SkillTurnPlan,
)
from eneo.skills.infrastructure.skill_repo_impl import (
    acquire_personal_default_fit_lock,
)
from eneo.spaces.api.space_models import WizardType
from eneo.spaces.space_repo import AssistantMCPServerProjection
from eneo.spaces.space_service import SpaceService
from eneo.templates.assistant_template.assistant_template_service import (
    AssistantTemplateService,
)
from eneo.tokens.token_utils import log_token_count_drift, measure_provider_input_tokens
from eneo.users.user import UserInDB
from eneo.workflows.step_repo import StepRepository

logger = get_logger(__name__)

# Personal defaults are validated tenant-wide; pages keep a fleet-sized
# tenant from being resident in memory all at once.
_PERSONAL_DEFAULT_VALIDATION_PAGE_SIZE = 100

_ON_DEMAND_REJECTION_DEFAULT = (
    "On-demand Skills cannot be enabled for this configuration"
)
_ON_DEMAND_REJECTION_MESSAGES: dict[SkillActivationFallbackReason, str] = {
    SkillActivationFallbackReason.SELECTIVE_ACTIVATION_DISABLED: (
        "On-demand Skills are disabled by the organisation runtime policy"
    ),
    SkillActivationFallbackReason.MODEL_LACKS_TOOL_CALLING: (
        "The selected completion model does not support on-demand Skills"
    ),
    SkillActivationFallbackReason.CATALOG_BUDGET_EXCEEDED: (
        "The on-demand Skill catalogue exceeds the configured context allowance"
    ),
    SkillActivationFallbackReason.TOKEN_MEASUREMENT_UNAVAILABLE: (
        "The selected completion model cannot measure the Skill catalogue exactly"
    ),
}
_ON_DEMAND_CANDIDATE_REJECTION_MESSAGES: dict[
    SkillActivationRejectionReason,
    str,
] = {
    SkillActivationRejectionReason.CONTEXT_LIMIT_EXCEEDED: (
        "exceeds the configured context allowance"
    ),
    SkillActivationRejectionReason.TOKEN_MEASUREMENT_UNAVAILABLE: (
        "cannot be measured exactly by the selected completion model"
    ),
    SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED: (
        "does not fit the selected completion model context"
    ),
}


if TYPE_CHECKING:
    from eneo.actors import ActorManager
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelPublic,
        CompletionModelResponse,
    )
    from eneo.assistants.references import ReferencesService
    from eneo.completion_models.application import CompletionModelCRUDService
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.domain.skill_activation import (
        SkillActivationRuntime,
    )
    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        CompletionModelAdapter,
    )
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from eneo.completion_models.infrastructure.web_search import (
        WebSearchResult,
    )
    from eneo.files.file_models import File
    from eneo.governance_policy.application.effective_config_service import (
        EffectiveConfigService,
    )
    from eneo.governance_policy.domain.policy_resolver import EffectiveConfig
    from eneo.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.sessions.session import SessionInDB
    from eneo.sessions.session_service import SessionService
    from eneo.skills.application.skill_service import SkillService
    from eneo.spaces.api.space_models import TemplateCreate
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class AssistantCompletionFileInputs:
    completion_message_files: list[File]
    completion_prompt_files: list[File]


AT_TAG_PATTERN = r"<eneo-at-tag: @[^>]+>"
REFERENCE_PATTERN = r'<inref id="([0-9a-f]{8})"/>'  # noqa


def clean_eneo_tag(input_string: str) -> str:
    return re.sub(AT_TAG_PATTERN, "", input_string)


TReference = TypeVar("TReference")


def get_references(
    response_string: str,
    info_blobs: Sequence[TReference],
    version: int = 1,
    get_id_func: Callable[[TReference], object] | None = None,
) -> list[TReference]:
    if version == 1:
        return list(info_blobs)

    # Preserve order, remove duplicates
    info_blob_ids = list(dict.fromkeys(re.findall(REFERENCE_PATTERN, response_string)))

    if get_id_func is None:

        def _default_get_id_func(blob: object) -> object:
            return getattr(blob, "id", getattr(blob, "info_blob_id", None))

        get_id_func = _default_get_id_func

    def _get_blob(blob_id: str):
        return next(
            (blob for blob in info_blobs if str(get_id_func(blob))[:8] == blob_id), None
        )

    blobs = [_get_blob(blob_id) for blob_id in info_blob_ids]

    return [blob for blob in blobs if blob is not None]


class AssistantService:
    def __init__(
        self,
        repo: AssistantRepository,
        space_repo: "SpaceRepository",
        user: UserInDB,
        service_repo: ServiceRepository,
        step_repo: StepRepository,
        completion_model_crud_service: "CompletionModelCRUDService",
        space_service: SpaceService,
        factory: AssistantFactory,
        prompt_service: PromptService,
        file_service: FileService,
        assistant_template_service: AssistantTemplateService,
        session_service: "SessionService",
        actor_manager: "ActorManager",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        completion_service: "CompletionService",
        references_service: "ReferencesService",
        icon_repo: IconRepository,
        org_space_assistant_role_repo: OrgSpaceAssistantRoleRepo,
        help_assistant_assignment_history_repo: HelpAssistantAssignmentHistoryRepo,
        skill_service: "SkillService",
        api_key_scope_revoker: ApiKeyScopeRevoker | None = None,
        effective_config_service: "EffectiveConfigService | None" = None,
    ):
        super().__init__()
        self.repo = repo
        self.space_repo = space_repo
        self.factory = factory
        self.user = user
        self.service_repo = service_repo
        self.step_repo = step_repo
        self.completion_model_crud_service = completion_model_crud_service
        self.space_service = space_service
        self.prompt_service = prompt_service
        self.file_service = file_service
        self.assistant_template_service = assistant_template_service
        self.session_service = session_service
        self.actor_manager = actor_manager
        self.integration_knowledge_repo = integration_knowledge_repo
        self.completion_service = completion_service
        self.references_service = references_service
        self.icon_repo = icon_repo
        self.org_space_assistant_role_repo = org_space_assistant_role_repo
        self.help_assistant_assignment_history_repo = (
            help_assistant_assignment_history_repo
        )
        self.skill_service = skill_service
        self.api_key_scope_revoker = api_key_scope_revoker
        self.effective_config_service = effective_config_service

    @property
    async def web_search(self):
        return WebSearch()

    def validate_space_assistant(
        self,
        space: "Space",
        assistant: Assistant,
        completion_model_changing: bool = True,
        knowledge_changing: bool = True,
    ):
        # validate completion model only if it was actually updated
        if completion_model_changing and assistant.completion_model is not None:
            if not space.is_completion_model_in_space(assistant.completion_model.id):
                raise BadRequestException("Completion model is not in space.")

        # validate groups and websites only if knowledge is changing
        if knowledge_changing:
            for group in assistant.collections:
                if not space.is_group_in_space(group.id):
                    raise BadRequestException("Group is not in space.")

            for website in assistant.websites:
                if not space.is_website_in_space(website.id):
                    raise BadRequestException("Website is not in space.")

        for integration_knowledge in assistant.integration_knowledge_list:
            if not space.is_integration_knowledge_in_space(
                integration_knowledge_id=integration_knowledge.id
            ):
                raise BadRequestException("Invalid integration knowledge")

    async def _resolve_effective_config(
        self, *, space: "Space", assistant: Assistant
    ) -> "EffectiveConfig | None":
        if (
            self.effective_config_service is None
            or not assistant.is_default
            or not space.is_personal()
        ):
            return None
        return await self.effective_config_service.resolve_for(
            assistant, space_is_personal=space.is_personal()
        )

    @staticmethod
    def _governed_base_instructions(
        assistant: Assistant, effective_config: "EffectiveConfig | None"
    ) -> str:
        if (
            effective_config is not None
            and effective_config.prompt_enforced
            and effective_config.enforced_prompt_text
        ):
            return effective_config.enforced_prompt_text
        return assistant.get_prompt_text()

    async def _resolve_assistant_skill_runtime(
        self,
        *,
        assistant: Assistant,
        effective_config: "EffectiveConfig | None",
        space_is_personal: bool,
    ) -> SkillRuntimeResolution:
        assistant_id = cast(UUID | None, assistant.id)
        direct_resolution = (
            await self.skill_service.resolve_assistant_bindings_for_runtime(
                assistant_id=assistant_id
            )
            if assistant_id is not None
            else SkillRuntimeResolution(eligible=(), blocked=())
        )

        if not (space_is_personal and assistant.is_default):
            return direct_resolution
        if direct_resolution.eligible or direct_resolution.blocked:
            raise BadRequestException(
                "Personal default Assistant has invalid direct Skill bindings"
            )
        if effective_config is None:
            return SkillRuntimeResolution(eligible=(), blocked=())
        return effective_config.governance_skill_resolution

    async def _create_skill_turn_plan(
        self,
        *,
        assistant: Assistant,
        effective_config: "EffectiveConfig | None",
        space_is_personal: bool,
    ) -> SkillTurnPlan:
        base_instructions = self._governed_base_instructions(
            assistant,
            effective_config,
        )
        resolution = await self._resolve_assistant_skill_runtime(
            assistant=assistant,
            effective_config=effective_config,
            space_is_personal=space_is_personal,
        )
        return await self.skill_service.create_turn_plan(
            base_instructions=base_instructions,
            resolution=resolution,
        )

    async def _ensure_governance_policy_allows_update(
        self,
        *,
        space: "Space",
        assistant: Assistant,
        completion_model_id: UUID | None,
        mcp_server_ids: list[UUID] | None,
        prompt_changing: bool = False,
        effective_config: "EffectiveConfig | None | NotProvided" = NOT_PROVIDED,
    ) -> None:
        # Nothing to validate → skip resolving the policy (and its DB round-trip).
        if (
            completion_model_id is None
            and mcp_server_ids is None
            and not prompt_changing
        ):
            return

        # _resolve_effective_config owns the is_default / personal-space / no-service
        # short-circuits and returns None when the policy does not apply. Callers
        # that already resolved it pass it in to avoid a second round-trip.
        if isinstance(effective_config, NotProvided):
            effective_config = await self._resolve_effective_config(
                space=space, assistant=assistant
            )
        if effective_config is None:
            return

        if prompt_changing and effective_config.prompt_enforced:
            raise BadRequestException(
                "Prompt is locked by personal assistant governance policy",
            )

        if completion_model_id is not None and effective_config.models_enforced:
            current_model_id = (
                assistant.completion_model.id
                if assistant.completion_model is not None
                else None
            )
            if completion_model_id != current_model_id:
                allowed_ids = {m.id for m in effective_config.available_models}
                if completion_model_id not in allowed_ids:
                    raise BadRequestException(
                        "Model not allowed by personal assistant governance policy",
                    )

        if mcp_server_ids is not None and effective_config.mcp_enforced:
            allowed_ids = {s.id for s in effective_config.available_mcp_servers}
            # Grandfather servers already attached: only newly-added servers
            # must satisfy the policy, mirroring the completion-model rule
            # above. This lets an admin tighten the whitelist without blocking
            # re-saves of assistants that still reference a now-disallowed
            # server.
            current_ids = {s.id for s in assistant.mcp_servers}
            disallowed = (set(mcp_server_ids) - current_ids) - allowed_ids
            if disallowed:
                raise BadRequestException(
                    "MCP servers not allowed by personal assistant governance policy",
                )

    async def _ensure_governance_policy_allows_mcp_server(
        self, *, space: "Space", assistant: Assistant, mcp_server_id: UUID
    ) -> None:
        await self._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=None,
            mcp_server_ids=[mcp_server_id],
        )

    async def create_assistant(
        self,
        name: str,
        space_id: UUID,
        template_data: Optional["TemplateCreate"] = None,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_create_assistants():
            raise UnauthorizedException(
                "User does not have permission to create assistants in this space"
            )

        completion_model = await self.get_completion_model(space=space)
        assert space.id is not None

        if not template_data:
            assistant = self.factory.create_assistant(
                name=name,
                user=self.user,
                space_id=space.id,
                completion_model=completion_model,
            )

            space.add_assistant(assistant)
            refreshed_space = await self.space_repo.update(space)
            assistant = refreshed_space.get_assistant(assistant.id)

        else:
            assistant = await self._create_from_template(
                space=space,
                template_data=template_data,
                completion_model=completion_model,
                name=name,
            )

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions  # type: ignore[return-value]

    async def _create_from_template(
        self,
        space: "Space",
        template_data: "TemplateCreate",
        completion_model: Optional["CompletionModel"],
        name: str | None = None,
    ):
        template = await self.assistant_template_service.get_assistant_template(
            assistant_template_id=template_data.id
        )

        if (
            template.completion_model
            and template.completion_model.id
            and space.is_completion_model_available(template.completion_model.id)
        ):
            completion_model = space.get_completion_model(template.completion_model.id)

        # Validate incoming data
        template.validate_assistant_wizard_data(template_data=template_data)
        assert space.id is not None

        attachments = await self.file_service.get_files_by_ids(
            file_ids=template_data.get_ids_by_type(wizard_type=WizardType.attachments)
        )
        # __init__ sets attachments directly, bypassing the setter, so enforce
        # the same persisted attachment contract explicitly on the template path.
        Assistant.validate_attachments(attachments)
        collections = [
            space.get_collection(collection_id=group_id)
            for group_id in template_data.get_ids_by_type(wizard_type=WizardType.groups)
        ]

        prompt = None
        if template.prompt_text:
            prompt = await self.prompt_service.create_prompt(text=template.prompt_text)

        template_kwargs: dict[str, object] = cast(
            dict[str, object], getattr(template, "completion_model_kwargs", {})
        )

        assistant = self.factory.create_assistant(
            name=name or template.name,
            user=self.user,
            space_id=space.id,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=ModelKwargs.model_validate(template_kwargs),
            attachments=attachments,
            collections=collections,
            template=template,
            description=template.description,
        )

        # Validate before persisting: the factory-built assistant already carries
        # the final model + attachments, so a set that doesn't fit is rejected
        # without leaving an invalid row behind.
        await self._validate_attachments_fit(assistant, space=space)

        space.add_assistant(assistant)
        refreshed_space = await self.space_repo.update(space)
        assistant = refreshed_space.get_assistant(assistant.id)

        return assistant

    async def _completion_prompt_files_for_model(
        self,
        persistent_attachments: list[File],
        completion_model: Optional["CompletionModel"],
    ) -> list[File]:
        if (
            completion_model is None
            or not completion_model.vision
            or not persistent_attachments
        ):
            return persistent_attachments

        return await self.file_service.with_derived_images(persistent_attachments)

    async def _validate_skill_activation_fit(
        self,
        *,
        validation_plan: SkillTurnPlan,
        candidate_skill_ids: frozenset[UUID],
        model: "CompletionModel",
        completion_prompt_files: list[File],
        effective_mcp_servers: list["MCPServer"],
        preflight_adapter: "CompletionModelAdapter | None" = None,
    ) -> None:
        """Validate one model-specific Skill plan using the runtime calculator."""
        runtime = validation_plan.to_activation_runtime(
            selected_model_route=model.get_model_route(),
            max_input_tokens=model.max_input_tokens,
            supports_tool_calling=model.supports_tool_calling,
        )
        snapshot = runtime.snapshot()
        if (
            candidate_skill_ids
            and snapshot.effective_mode is not SkillTurnEffectiveMode.SELECTIVE
        ):
            message = (
                _ON_DEMAND_REJECTION_MESSAGES.get(
                    snapshot.fallback_reason,
                    _ON_DEMAND_REJECTION_DEFAULT,
                )
                if snapshot.fallback_reason is not None
                else _ON_DEMAND_REJECTION_DEFAULT
            )
            raise SkillActivationUnavailableException(message)

        assessments = runtime.assess_on_demand_candidates(candidate_skill_ids)
        rejected_assessment = next(
            (
                assessment
                for assessment in assessments
                if assessment.rejection_reason is not None
            ),
            None,
        )
        if rejected_assessment is not None:
            rejection_reason = rejected_assessment.rejection_reason
            assert rejection_reason is not None
            raise BadRequestException(
                f'on-demand Skill "{rejected_assessment.display_name}" '
                + _ON_DEMAND_CANDIDATE_REJECTION_MESSAGES.get(
                    rejection_reason,
                    _ON_DEMAND_REJECTION_DEFAULT,
                )
            )

        assert_prompt_and_files_fit_context(
            max_input_tokens=model.max_input_tokens,
            model_name=model.get_model_route(),
            prompt_text=runtime.prompt,
            files=completion_prompt_files,
        )

        if not candidate_skill_ids and not effective_mcp_servers:
            return

        provider_input = (
            await self.completion_service.prepare_skill_activation_preflight(
                model=cast("AICompletionModel", model),
                prompt=runtime.prompt,
                prompt_files=completion_prompt_files,
                mcp_servers=effective_mcp_servers,
                skill_runtime=runtime,
                adapter=preflight_adapter,
            )
        )
        provider_input_token_limit = attachment_token_ceiling(model.max_input_tokens)
        baseline_measurement = measure_provider_input_tokens(
            provider_input.messages,
            provider_input.tools,
            model.get_model_route(),
        )
        if baseline_measurement.tokens > provider_input_token_limit:
            raise BadRequestException(
                "The Assistant prompt, files, and tools exceed the completion "
                "model context window"
            )
        provider_assessments = runtime.assess_provider_payload_candidates(
            candidate_skill_ids,
            messages=provider_input.messages,
            provider_tools=provider_input.tools,
            provider_input_token_limit=provider_input_token_limit,
        )
        rejected_provider_assessment = next(
            (
                assessment
                for assessment in provider_assessments
                if assessment.rejection_reason is not None
            ),
            None,
        )
        if rejected_provider_assessment is not None:
            rejection_reason = rejected_provider_assessment.rejection_reason
            assert rejection_reason is not None
            message = _ON_DEMAND_CANDIDATE_REJECTION_MESSAGES.get(
                rejection_reason,
                _ON_DEMAND_REJECTION_DEFAULT,
            )
            raise BadRequestException(
                f'on-demand Skill "{rejected_provider_assessment.display_name}" '
                f"{message}"
            )

    async def _validate_attachments_fit(
        self,
        assistant: Assistant,
        *,
        space: "Space",
        on_demand_skill_ids_requiring_validation: frozenset[UUID] = frozenset(),
        validate_all_on_demand_candidates: bool = False,
        mcp_servers_override: list["MCPServer"] | None = None,
    ) -> None:
        """Reject saving when the system prompt + persistent attachments don't
        fit the model's context window with room left to ask a question.

        Validates the model, prompt and file set that ask() will ACTUALLY send,
        so the save can't admit a configuration the request would then reject:
        - Governance: for a governed personal-default assistant, the
          governance-effective model and enforced prompt — not the assistant's
          own — mirroring the resolution in ask().
        - Vision: the persistent attachments expanded with their
          document-derived images.

        Attachments are sent whole (never truncated), so a set that doesn't fit
        can't run — a clear rejection beats silently sending part of a document.
        On-demand candidates are staged one at a time against the provider-visible
        baseline, including the activation transcript and configured MCP schemas.
        Combinations and live per-user MCP narrowing remain turn-time decisions.
        Skipped only when no model is resolved."""
        await acquire_personal_default_fit_lock(
            session=self.repo.session,
            tenant_id=self.user.tenant_id,
            shared=True,
        )
        # Mirror ask()'s governance resolution so the fit check uses the model
        # and prompt the request will really send, not the assistant's own.
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )
        skill_plan = await self._create_skill_turn_plan(
            assistant=assistant,
            effective_config=effective_config,
            space_is_personal=space.is_personal(),
        )
        validation_plan = (
            skill_plan.for_full_save_validation()
            if validate_all_on_demand_candidates
            else skill_plan
        )
        candidate_ids = set(on_demand_skill_ids_requiring_validation)
        if validate_all_on_demand_candidates:
            candidate_ids.update(
                binding.binding.skill_id
                for binding in validation_plan.available
                if binding.binding.activation_mode is SkillActivationMode.ON_DEMAND
            )
        candidate_skill_ids = frozenset(candidate_ids)
        model = self._context_model(assistant, effective_config=effective_config)
        if model is None:
            if candidate_skill_ids:
                raise BadRequestException(
                    "Choose a completion model before enabling on-demand Skills"
                )
            return

        completion_prompt_files = await self._completion_prompt_files_for_model(
            persistent_attachments=assistant.attachments,
            completion_model=model,
        )
        if effective_config is not None and effective_config.mcp_enforced:
            effective_mcp_servers = effective_config.available_mcp_servers
        elif mcp_servers_override is not None:
            effective_mcp_servers = mcp_servers_override
        else:
            effective_mcp_servers = assistant.mcp_servers
        if assistant.has_knowledge():
            effective_mcp_servers = []
        await self._validate_skill_activation_fit(
            validation_plan=validation_plan,
            candidate_skill_ids=candidate_skill_ids,
            model=model,
            completion_prompt_files=completion_prompt_files,
            effective_mcp_servers=effective_mcp_servers,
        )

    async def assert_assistant_fits_candidate_pin(
        self,
        *,
        assistant: Assistant,
        space_is_personal: bool,
        candidate: PersonalChatPinOverride,
        candidate_binding: ResolvedSkillBinding,
        resolution: SkillRuntimeResolution,
        runtime_policy: SkillRuntimePolicy,
        preflight_adapters: dict[UUID, "CompletionModelAdapter"],
    ) -> AssistantPinAdvanceIncompatibleReason | None:
        """Token-limit fit refusals map to CONTEXT_WINDOW for now."""
        assert not (space_is_personal and assistant.is_default)
        assert candidate_binding.skill_id == candidate.skill_id
        assert candidate_binding.skill_revision_id == candidate.to_revision_id

        current_binding = next(
            (
                binding
                for binding in (*resolution.eligible, *resolution.blocked)
                if binding.skill_id == candidate.skill_id
                and binding.skill_revision_id == candidate.from_revision_id
            ),
            None,
        )
        assert current_binding is not None
        resolved_candidate = replace(
            candidate_binding,
            position=current_binding.position,
            activation_mode=current_binding.activation_mode,
        )
        candidate_resolution = SkillRuntimeResolution(
            eligible=tuple(
                resolved_candidate if binding is current_binding else binding
                for binding in resolution.eligible
            ),
            blocked=tuple(
                resolved_candidate if binding is current_binding else binding
                for binding in resolution.blocked
            ),
        )
        validation_plan = SkillTurnPlan.create(
            base_instructions=assistant.get_prompt_text(),
            resolution=candidate_resolution,
            policy=runtime_policy,
        ).for_full_save_validation()
        candidate_skill_ids = frozenset(
            binding.binding.skill_id
            for binding in validation_plan.available
            if binding.binding.activation_mode is SkillActivationMode.ON_DEMAND
        )
        model = assistant.completion_model
        if model is None:
            if candidate_skill_ids:
                return AssistantPinAdvanceIncompatibleReason.CONTEXT_WINDOW
            return None
        completion_prompt_files = await self._completion_prompt_files_for_model(
            persistent_attachments=assistant.attachments,
            completion_model=model,
        )
        effective_mcp_servers = (
            [] if assistant.has_knowledge() else assistant.mcp_servers
        )
        try:
            await self._validate_skill_activation_fit(
                validation_plan=validation_plan,
                candidate_skill_ids=candidate_skill_ids,
                model=model,
                completion_prompt_files=completion_prompt_files,
                effective_mcp_servers=effective_mcp_servers,
                preflight_adapter=(
                    preflight_adapters[model.id]
                    if candidate_skill_ids or effective_mcp_servers
                    else None
                ),
            )
        except SkillActivationUnavailableException:
            return AssistantPinAdvanceIncompatibleReason.ACTIVATION_UNAVAILABLE
        except BadRequestException:
            return AssistantPinAdvanceIncompatibleReason.CONTEXT_WINDOW
        return None

    @staticmethod
    def _context_model(
        assistant: Assistant, *, effective_config: "EffectiveConfig | None"
    ) -> "CompletionModel | None":
        model = assistant.completion_model
        if effective_config is None or not effective_config.models_enforced:
            return model
        resolved_model = select_effective_completion_model(
            current_model=model, effective_config=effective_config
        )
        if resolved_model is None:
            raise BadRequestException(
                "Personal assistant governance policy has no allowed models — "
                "contact admin"
            )
        return resolved_model

    async def assert_personal_default_governance_context_fit(
        self,
        *,
        personal_chat_pin_override: PersonalChatPinOverride | None = None,
    ) -> None:
        """Reject a candidate governance baseline that existing chats cannot run.

        Policy and Skill writes are staged in the request transaction before
        this method runs, so the effective-config read sees the candidate state.
        The policy catalogs are identical for every personal default Assistant;
        resolve them once, then select the actual runtime model per Assistant.
        The scan is intentionally linear because prompts and attachments differ,
        and runs only for admin changes that alter the persistent baseline.
        Disabling governance may still fail closed if the stored baseline that
        becomes effective is itself too large for its model.
        """
        if self.effective_config_service is None:
            raise RuntimeError(
                "EffectiveConfigService is required for governance context preflight"
            )
        effective_config = (
            await self.effective_config_service.resolve_personal_default()
            if personal_chat_pin_override is None
            else await self.effective_config_service.resolve_personal_default(
                personal_chat_pin_override=personal_chat_pin_override
            )
        )
        policy_plan = await self.skill_service.create_turn_plan(
            base_instructions=effective_config.enforced_prompt_text or "",
            resolution=effective_config.governance_skill_resolution,
        )
        policy_validation_plan = policy_plan.for_full_save_validation()
        candidate_skill_ids = frozenset(
            frozen.binding.skill_id
            for frozen in policy_validation_plan.available
            if frozen.binding.activation_mode is SkillActivationMode.ON_DEMAND
        )
        if candidate_skill_ids and not effective_config.models_bounded_for_on_demand:
            raise BadRequestException(
                "On-demand Skills require explicit completion models; "
                "provider-wide or unrestricted model access cannot be validated safely"
            )

        # Always preload: the baseline provider-payload measurement needs an
        # adapter for MCP-configured always-only defaults too, and the batch
        # loader costs one read per distinct provider — a per-assistant
        # _get_adapter fallback inside the tenant-wide page walk does not.
        preflight_adapters: dict[
            UUID, CompletionModelAdapter
        ] = await self.completion_service.load_skill_activation_preflight_adapters(
            [
                cast("AICompletionModel", model)
                for model in effective_config.available_models
            ]
        )
        if candidate_skill_ids:
            for model in effective_config.available_models:
                await self._validate_skill_activation_fit(
                    validation_plan=policy_validation_plan,
                    candidate_skill_ids=candidate_skill_ids,
                    model=model,
                    completion_prompt_files=[],
                    effective_mcp_servers=(
                        effective_config.available_mcp_servers
                        if effective_config.mcp_enforced
                        else []
                    ),
                    preflight_adapter=preflight_adapters[model.id],
                )

        # Walk the tenant's personal defaults one bounded page at a time — a
        # fleet-sized tenant must never be resident all at once. The MCP
        # projection is scoped to each page for the same reason.
        page_cursor: tuple[datetime, UUID] | None = None
        while True:
            page = await self.repo.get_personal_defaults_page(
                tenant_id=self.user.tenant_id,
                limit=_PERSONAL_DEFAULT_VALIDATION_PAGE_SIZE,
                after=page_cursor,
            )
            await self._validate_personal_default_page(
                validation_inputs=page.items,
                effective_config=effective_config,
                policy_plan=policy_plan,
                candidate_skill_ids=candidate_skill_ids,
                preflight_adapters=preflight_adapters,
            )
            if page.next_after is None:
                break
            page_cursor = page.next_after

    async def _validate_personal_default_page(
        self,
        *,
        validation_inputs: list[PersonalDefaultValidationInput],
        effective_config: "EffectiveConfig",
        policy_plan: SkillTurnPlan,
        candidate_skill_ids: frozenset[UUID],
        preflight_adapters: dict[UUID, "CompletionModelAdapter"],
    ) -> None:
        """Validate one page of personal defaults against the governed plan."""
        projected_mcp_servers: dict[UUID, list[MCPServer]] = {}
        if not effective_config.mcp_enforced:
            mcp_projections = [
                AssistantMCPServerProjection(
                    space_id=validation_input.assistant.space_id,
                    assistant_id=validation_input.assistant.id,
                    mcp_servers=validation_input.configured_mcp_servers,
                )
                for validation_input in validation_inputs
                if validation_input.configured_mcp_servers
                and not validation_input.has_knowledge
            ]
            if mcp_projections:
                projected_mcp_servers = (
                    await self.space_repo.project_assistants_mcp_servers(
                        mcp_projections
                    )
                )

        for validation_input in validation_inputs:
            assistant = validation_input.assistant
            # Reuse the policy loaded above; the service wrapper would fetch it again.
            assistant_plan = SkillTurnPlan.create(
                base_instructions=self._governed_base_instructions(
                    assistant, effective_config
                ),
                resolution=effective_config.governance_skill_resolution,
                policy=policy_plan.policy,
            )
            model = self._context_model(assistant, effective_config=effective_config)
            if model is None:
                continue
            completion_prompt_files = await self._completion_prompt_files_for_model(
                persistent_attachments=assistant.attachments,
                completion_model=model,
            )
            effective_mcp_servers: list["MCPServer"] = []
            if not validation_input.has_knowledge:
                if effective_config.mcp_enforced:
                    effective_mcp_servers = effective_config.available_mcp_servers
                elif validation_input.configured_mcp_servers:
                    assert assistant.id is not None
                    effective_mcp_servers = projected_mcp_servers[assistant.id]
            preflight_adapter = (
                preflight_adapters.get(model.id)
                if candidate_skill_ids or effective_mcp_servers
                else None
            )
            await self._validate_skill_activation_fit(
                validation_plan=assistant_plan.for_full_save_validation(),
                candidate_skill_ids=candidate_skill_ids,
                model=model,
                completion_prompt_files=completion_prompt_files,
                effective_mcp_servers=effective_mcp_servers,
                preflight_adapter=preflight_adapter,
            )

    async def _assert_message_attachments_fit(
        self,
        *,
        assistant: "Assistant",
        model: "CompletionModel",
        prompt_text: str,
        files: list["File"],
        validate_persistent_baseline: bool = False,
    ) -> None:
        """Per-message ask-time guard. Persistent attachments are gated on save,
        but a chat message's own uploads are not — and they are now inlined whole
        on the send and on every later replay. Count the persistent baseline plus
        this message's files (both expanded with derived images, as the request
        sends them) against the same ceiling, so an upload that can't fit is
        rejected up front instead of failing at the provider. A zero-Skill turn
        with no uploads keeps the existing fast path because its baseline was
        validated on save. Skill turns recheck the baseline because bindings can
        change independently of the Assistant. History is budget-evicted
        downstream."""
        if not files and not validate_persistent_baseline:
            return
        persistent_files = await self._completion_prompt_files_for_model(
            persistent_attachments=assistant.attachments,
            completion_model=model,
        )
        message_files = (
            await self.file_service.with_derived_images(files)
            if model.vision
            else files
        )
        assert_prompt_and_files_fit_context(
            max_input_tokens=model.max_input_tokens,
            model_name=model.name,
            prompt_text=prompt_text,
            files=persistent_files + message_files,
        )

    async def get_completion_model(self, space: "Space") -> Optional["CompletionModel"]:
        """Get a completion model for the space. Returns None if no model is available."""
        model = space.get_default_completion_model()
        if model:
            return model  # type: ignore[return-value]

        if space.completion_models:
            try:
                model = space.get_latest_completion_model()
                if model:
                    return model  # type: ignore[return-value]
            except Exception:
                pass

        # Try to get tenant default model
        return await self.completion_model_crud_service.get_default_completion_model()  # type: ignore[return-value]

    async def create_default_assistant(self, name: str, space: "Space"):
        cm = space.get_default_completion_model()
        assert space.id is not None

        if cm and not space.is_completion_model_in_space(cm.id):
            space.add_completion_model(cm)
            await self.space_repo.update(space)

        return self.factory.create_assistant(
            name=name,
            user=self.user,
            space_id=space.id,
            completion_model=cm,
            is_default=True,
        )

    async def update_assistant(
        self,
        assistant_id: UUID,
        name: str | None = None,
        prompt: PromptCreate | None = None,
        completion_model_id: UUID | None = None,
        completion_model_kwargs: ModelKwargs | None = None,
        logging_enabled: bool | None = None,
        groups: list[UUID] | None = None,
        websites: list[UUID] | None = None,
        integration_knowledge_ids: list[UUID] | None = None,
        mcp_server_ids: list[UUID] | None = None,
        mcp_tools: list[tuple[UUID, bool]] | None = None,
        attachment_ids: list[UUID] | None = None,
        description: Union[str, None, NotProvided] = NOT_PROVIDED,
        insight_enabled: Optional[bool] = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        metadata_json: Union[dict[str, object], None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
        skill_binding_intents: list[SkillBindingIntent] | None = None,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        if logging_enabled:
            validate_permission(self.user, Permission.ADMIN)

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        # Check if user has permission to toggle insights
        if insight_enabled is not None:
            if not actor.can_toggle_insight():
                raise UnauthorizedException("Only admins can toggle insights")

        assistant = space.get_assistant(assistant_id=assistant_id)

        # Access to the personal default assistant requires PERSONAL_CHAT.
        # That permission permits model selection only; broader configuration
        # changes additionally require ASSISTANTS below.
        is_personal_default = (
            space.is_personal()
            and space.default_assistant is not None
            and assistant.id == space.default_assistant.id
        )

        can_edit_default = (
            actor.can_edit_default_assistant() if is_personal_default else False
        )
        can_edit_assistants = actor.can_edit_assistants()
        if not (can_edit_default if is_personal_default else can_edit_assistants):
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "update",
                    "auth_layer": "domain_policy",
                },
            )

        extended_update_requested = any(
            value is not None
            for value in (
                name,
                prompt,
                completion_model_kwargs,
                logging_enabled,
                groups,
                websites,
                integration_knowledge_ids,
                mcp_server_ids,
                mcp_tools,
                attachment_ids,
                insight_enabled,
                skill_binding_intents,
            )
        ) or any(
            is_provided(value)
            for value in (
                description,
                data_retention_days,
                metadata_json,
                icon_id,
            )
        )
        if (
            is_personal_default
            and extended_update_requested
            and not can_edit_assistants
        ):
            raise UnauthorizedException(
                "The personal_chat permission only allows changing the "
                "personal assistant's completion model.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "update",
                    "auth_layer": "domain_policy",
                },
            )

        update_effective_config: "EffectiveConfig | None | NotProvided" = NOT_PROVIDED
        if prompt is not None:
            update_effective_config = await self._resolve_effective_config(
                space=space, assistant=assistant
            )
            await self._ensure_governance_policy_allows_update(
                space=space,
                assistant=assistant,
                completion_model_id=None,
                mcp_server_ids=None,
                prompt_changing=True,
                effective_config=update_effective_config,
            )

        prompt_obj: Prompt | None = None
        if prompt is not None:
            # When the update carries a `prompt` field, persist it — empty
            # text included. An empty string is a deliberate "clear the
            # prompt" action by the user (they emptied the textarea on
            # purpose), not a missing field; the outer ``prompt is not
            # None`` check above already distinguishes "this update does
            # not touch the prompt" from "set the prompt to X". Treating
            # ``""`` as falsy here silently kept the previous prompt and
            # reverted the user's clear-and-save.
            #
            # Attribute the prompt to the assistant's owner, not the
            # caller. Keeps service-key edits FK-safe (synthetic id has
            # no `users` row) and makes admin edits to others'
            # assistants attribute correctly.
            prompt_owner_id = (
                assistant.user.id if assistant.user is not None else self.user.id
            )
            prompt_obj = await self.prompt_service.create_prompt(
                prompt.text,
                prompt.description,
                owner_user_id=prompt_owner_id,
            )

        completion_model = None
        if completion_model_id is not None:
            if not space.is_completion_model_available(completion_model_id):
                raise BadRequestException(
                    "The completion model is not enabled in the space."
                )
            completion_model = space.get_completion_model(completion_model_id)

        attachments = None
        if attachment_ids is not None:
            attachments = await self.file_service.get_files_by_ids(attachment_ids)

        group_entities = None
        if groups is not None:
            group_entities = [
                space.get_collection(collection_id=group_id) for group_id in groups
            ]

        website_entities = None
        if websites is not None:
            website_entities = [
                space.get_website(website_id=website_id) for website_id in websites
            ]

        integration_knowledge_list = None
        if integration_knowledge_ids is not None:
            integration_knowledge_list = [
                space.get_integration_knowledge(
                    integration_knowledge_id=integration_knowledge_id
                )
                for integration_knowledge_id in integration_knowledge_ids
            ]

        # Validate MCP server assignments against tenant + space boundaries.
        mcp_effective_config: "EffectiveConfig | None | NotProvided" = (
            update_effective_config
        )
        if mcp_server_ids is not None:
            import sqlalchemy as sa

            from eneo.database.tables.mcp_server_table import (
                MCPServers as MCPServersTable,
            )

            mcp_servers_query = (
                sa.select(MCPServersTable.id)
                .where(MCPServersTable.tenant_id == self.user.tenant_id)
                .where(MCPServersTable.is_enabled == True)  # noqa: E712
                .where(MCPServersTable.id.in_(mcp_server_ids))
            )
            mcp_servers_result = await self.repo.session.execute(mcp_servers_query)
            enabled_server_ids = {row[0] for row in mcp_servers_result.fetchall()}

            missing_tenant_enabled_ids = [
                str(server_id)
                for server_id in mcp_server_ids
                if server_id not in enabled_server_ids
            ]
            if missing_tenant_enabled_ids:
                raise BadRequestException(
                    "MCP server(s) are not enabled for this tenant: "
                    + ", ".join(missing_tenant_enabled_ids)
                )

            # For a personal default assistant under an active MCP policy, the
            # governance whitelist (enforced just below) is the source of truth.
            if isinstance(mcp_effective_config, NotProvided):
                mcp_effective_config = await self._resolve_effective_config(
                    space=space, assistant=assistant
                )
            mcp_governed = (
                mcp_effective_config is not None and mcp_effective_config.mcp_enforced
            )
            if not mcp_governed:
                # Validate space membership against the space read model — the
                # same source the editor/UI uses to offer servers. For a personal
                # space that is every tenant-enabled server (space_factory exposes
                # them all); for a shared space it is the spaces_mcp_servers
                # mapping. Do NOT query spaces_mcp_servers directly: that table is
                # seeded once at space creation and never back-filled, so for a
                # personal space it goes stale and wrongly rejects servers enabled
                # after the space was created (#500).
                missing_space_ids = [
                    str(server_id)
                    for server_id in mcp_server_ids
                    if not space.is_mcp_server_in_space(server_id)
                ]
                if missing_space_ids:
                    raise BadRequestException(
                        "MCP server(s) are not assigned to this assistant's space: "
                        + ", ".join(missing_space_ids)
                    )

        await self._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=completion_model_id,
            mcp_server_ids=mcp_server_ids,
            prompt_changing=False,
            effective_config=mcp_effective_config,
        )

        mcp_servers_for_validation: list["MCPServer"] | None = None
        if mcp_server_ids is not None or mcp_tools is not None:
            assert space.id is not None
            selected_ids = (
                set(mcp_server_ids)
                if mcp_server_ids is not None
                else {server.id for server in assistant.mcp_servers}
            )
            source_servers = (
                space.mcp_servers
                if mcp_server_ids is not None
                else assistant.mcp_servers
            )
            mcp_servers_for_validation = (
                await self.space_repo.project_assistant_mcp_servers(
                    space_id=space.id,
                    assistant_id=assistant_id,
                    mcp_servers=[
                        server for server in source_servers if server.id in selected_ids
                    ],
                    tool_settings=mcp_tools,
                )
            )

        # Store MCP server IDs and tool settings for repository to handle.
        setattr(assistant, "_mcp_server_ids", mcp_server_ids)
        setattr(assistant, "_mcp_tool_settings", mcp_tools)

        assistant.update(
            name=name,
            prompt=prompt_obj,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            attachments=attachments,
            logging_enabled=logging_enabled,
            collections=group_entities,
            websites=website_entities,
            integration_knowledge_list=integration_knowledge_list,
            description=description,
            insight_enabled=insight_enabled,
            data_retention_days=data_retention_days,
            metadata_json=metadata_json,
            icon_id=icon_id,
        )

        # Validate mutual exclusivity: knowledge and MCP servers cannot both be active.
        # Only check when either side is being updated to avoid false positives on
        # unrelated updates (e.g. renaming an assistant).
        knowledge_changing = (
            groups is not None
            or websites is not None
            or integration_knowledge_ids is not None
        )
        mcp_changing = mcp_server_ids is not None
        if knowledge_changing or mcp_changing:
            will_have_mcp = (
                mcp_server_ids is not None and len(mcp_server_ids) > 0
            ) or (mcp_server_ids is None and assistant.has_mcp())
            if assistant.has_knowledge() and will_have_mcp:
                raise BadRequestException(
                    "Knowledge and MCP servers cannot both be active on an assistant. "
                    "Remove one before enabling the other."
                )

        # Only validate space references when the relevant fields are actually changing
        self.validate_space_assistant(
            space=space,
            assistant=assistant,
            completion_model_changing=completion_model is not None,
            knowledge_changing=knowledge_changing,
        )

        on_demand_skill_ids_requiring_validation: frozenset[UUID] = frozenset()
        if skill_binding_intents is not None:
            replacement = await self.skill_service.replace_assistant_bindings(
                space_id=assistant.space_id,
                assistant_id=assistant_id,
                intents=skill_binding_intents,
            )
            on_demand_skill_ids_requiring_validation = (
                replacement.on_demand_skill_ids_requiring_validation
            )

        # Validate before persisting (the in-memory assistant already reflects the
        # final model + prompt + attachments from update() above), so a save that
        # no longer fits — after switching to a smaller-context model OR enlarging
        # the prompt (which counts toward the ceiling) — is rejected without
        # committing an invalid row.
        if (
            attachments is not None
            or completion_model is not None
            or prompt_obj is not None
            or skill_binding_intents is not None
            or mcp_server_ids is not None
            or mcp_tools is not None
        ):
            await self._validate_attachments_fit(
                assistant,
                space=space,
                on_demand_skill_ids_requiring_validation=(
                    on_demand_skill_ids_requiring_validation
                ),
                validate_all_on_demand_candidates=(
                    attachments is not None
                    or completion_model is not None
                    or prompt_obj is not None
                    or skill_binding_intents is not None
                    or mcp_server_ids is not None
                    or mcp_tools is not None
                ),
                mcp_servers_override=mcp_servers_for_validation,
            )

        refreshed_space = await self.space_repo.update(space)
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    def _authorize_read_assistant(self, space: "Space", assistant: Assistant) -> None:
        """Enforce read authorization for an assistant in a space.

        The personal chat is the personal space's default assistant — it is
        gated by PERSONAL_CHAT (via can_read_default_assistant), not ASSISTANTS,
        so a baseline role can use the chat without managing assistants. Every
        read path (get_assistant, the effective-config serialization, and the
        preflight model resolution) must apply this same carve-out, or the exact
        users this feature targets get a spurious 403.
        """
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        is_personal_default = (
            space.is_personal()
            and space.default_assistant is not None
            and assistant.id == space.default_assistant.id
        )
        can_read = (
            actor.can_read_default_assistant()
            if is_personal_default
            else actor.can_read_assistants()
        )
        if not can_read:
            raise UnauthorizedException(
                "You do not have permission to read assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

    async def get_assistant(
        self, assistant_id: UUID
    ) -> tuple[Assistant, list[ResourcePermission]]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        self._authorize_read_assistant(space=space, assistant=assistant)

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions  # type: ignore[return-value]

    async def get_assistant_with_effective_config(
        self, assistant_id: UUID
    ) -> tuple[Assistant, list[ResourcePermission], "EffectiveConfig | None"]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        self._authorize_read_assistant(space=space, assistant=assistant)

        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )

        return assistant, permissions, effective_config

    async def get_effective_completion_model(
        self, assistant_id: UUID
    ) -> "CompletionModel | None":
        """The model that will actually answer for this assistant, honoring a
        personal-assistant models policy.

        Mirrors the resolution `ask()` applies so read-time preflight and
        ask-time enforcement never disagree about which model a request uses.
        """
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        # Preflight is reachable with an arbitrary assistant_id; enforce the same
        # read authorization get_assistant() applies so it can't probe assistants
        # the caller cannot access.
        self._authorize_read_assistant(space=space, assistant=assistant)
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )
        return select_effective_completion_model(
            current_model=assistant.completion_model,
            effective_config=effective_config,
        )

    async def get_preflight_baseline(
        self, assistant_id: UUID
    ) -> tuple[str, list[File]]:
        """The always-present cost of an assistant: its system prompt text and
        its persistent attachments, which ride along on every question.

        Preflight uses this so the meter can show the baseline, not just the
        per-message delta. Applies the same read authorization as
        get_effective_completion_model (including the personal-default carve-out)
        so it can't probe assistants the caller cannot access.
        """
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        self._authorize_read_assistant(space=space, assistant=assistant)
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )
        skill_plan = await self._create_skill_turn_plan(
            assistant=assistant,
            effective_config=effective_config,
            space_is_personal=space.is_personal(),
        )
        model = self._context_model(assistant, effective_config=effective_config)
        prompt = skill_plan.composition.prompt
        if model is not None:
            prompt = skill_plan.to_activation_runtime(
                selected_model_route=model.get_model_route(),
                max_input_tokens=model.max_input_tokens,
                supports_tool_calling=model.supports_tool_calling,
            ).prompt

        return prompt, assistant.attachments

    async def get_skill_configuration(
        self,
        *,
        space_id: UUID,
        assistant_id: UUID,
    ) -> AssistantSkillConfigurationProjection:
        """Return saved Assistant bindings and their exact initial runtime state.

        The binding projection intentionally runs first because it owns both
        Assistant and Skill-read authorization. Runtime resolution then follows
        the same turn-plan path as ask and save validation.
        """
        bindings = await self.skill_service.list_assistant_binding_projections(
            space_id=space_id,
            assistant_id=assistant_id,
        )
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        if space.is_personal() and assistant.is_default:
            return AssistantSkillConfigurationProjection(
                bindings=tuple(bindings),
                runtime=None,
            )

        effective_config = await self._resolve_effective_config(
            space=space,
            assistant=assistant,
        )
        model = self._context_model(assistant, effective_config=effective_config)
        if model is None:
            return AssistantSkillConfigurationProjection(
                bindings=tuple(bindings),
                runtime=None,
            )

        skill_plan = await self._create_skill_turn_plan(
            assistant=assistant,
            effective_config=effective_config,
            space_is_personal=space.is_personal(),
        )
        runtime = skill_plan.to_activation_runtime(
            selected_model_route=model.get_model_route(),
            max_input_tokens=model.max_input_tokens,
            supports_tool_calling=model.supports_tool_calling,
        )
        return AssistantSkillConfigurationProjection(
            bindings=tuple(bindings),
            runtime=AssistantSkillRuntimeProjection(
                effective_model_id=model.id,
                snapshot=runtime.snapshot(),
            ),
        )

    async def is_help_assistant(self, assistant_id: UUID) -> bool:
        """Whether ``assistant_id`` currently fills a Help Assistant role.

        True iff an active row in ``org_space_assistant_roles`` points at it.
        The single-assistant GET endpoint surfaces this so the edit UI can
        explain why logging is permanently disabled on helpers (PRD §6, §9).
        Mirrors the "active" half of the ``assert_not_helper_assistant`` guard.
        """
        return await self.org_space_assistant_role_repo.exists_active_for_assistant(
            assistant_id
        )

    async def get_help_assistant(self, assistant_id: UUID) -> Assistant:
        """Load a Help Assistant by id, bypassing the space-actor read gate.

        Help Assistants live in the org-space, whose only members are the
        tenant admins added by ``SpaceService.ensure_org_admin_members`` —
        regular users are never org-space members and therefore cannot pass
        the ``actor.can_read_assistants()`` check in :meth:`get_assistant`.
        But the Prompt Guide is, by design (PRD §5/§6/§10), usable by *any*
        authenticated user who has ``EDIT`` rights on the *target* assistant:
        their authorization is governed by those target-edit rights plus the
        role's ``is_enabled`` / ``is_visible_to_users`` flags — all enforced
        by the caller — **not** by org-space membership.

        This loads the assistant exactly as :meth:`get_assistant` does, minus
        the org-space read gate. To keep the bypass narrow — only the assistant
        *designated by a help-assistant role* is readable this way, never an
        arbitrary org-space assistant — it first asserts the id currently
        fills, or formerly filled, a help-assistant role. Anything else raises
        :class:`NotFoundException`, so this can neither be used as a generic
        permission-skipping read nor to probe org-space assistants.

        Callers are :class:`HelperRunService` (``run`` / ``continue_turn``) and
        the availability endpoint, always with an id resolved server-side from
        an active ``OrgSpaceAssistantRole`` or an existing ``HelperRun`` — never
        a client-supplied assistant id. ``continue_turn`` may legitimately load
        a *former* helper (the role was reassigned mid-conversation), which is
        why the assignment-history branch counts.
        """
        is_active_helper = (
            await self.org_space_assistant_role_repo.exists_active_for_assistant(
                assistant_id
            )
        )
        is_former_helper = (
            await self.help_assistant_assignment_history_repo.exists_for_assistant(
                assistant_id
            )
        )
        if not (is_active_helper or is_former_helper):
            raise NotFoundException(
                "Assistant is not a help assistant; refusing privileged read."
            )

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        return space.get_assistant(assistant_id=assistant_id)

    async def get_assistants(
        self,
        name: str | None = None,
        for_tenant: bool = False,
        space_id_filter: UUID | None = None,
        assistant_id_filter: UUID | None = None,
    ) -> list[Assistant]:
        if for_tenant:
            return await self.get_tenant_assistants(name)

        return await self.repo.get_for_user(
            self.user.id,
            search_query=name,
            space_id=space_id_filter,
            assistant_id=assistant_id_filter,
        )

    @validate_permissions(Permission.ADMIN)
    async def get_tenant_assistants(
        self,
        name: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[Assistant]:
        assistants = await self.repo.get_for_tenant(
            tenant_id=self.user.tenant_id,
            search_query=name,
            start_date=start_date,
            end_date=end_date,
        )
        return assistants

    async def delete_assistant(self, assistant_id: UUID):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_delete_assistants():
            raise UnauthorizedException(
                "You do not have permission to delete assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "delete",
                    "auth_layer": "domain_policy",
                },
            )

        assistant = space.get_assistant(assistant_id=assistant_id)
        icon_id = assistant.icon_id

        if self.api_key_scope_revoker is not None:
            try:
                await self.api_key_scope_revoker.revoke_scope(
                    scope_type=ApiKeyScopeType.ASSISTANT,
                    scope_id=assistant_id,
                    reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                    reason_text="Assistant deleted",
                )
            except Exception:
                logger.exception(
                    "Failed to revoke API keys for deleted assistant",
                    extra={"assistant_id": str(assistant_id)},
                )

        space.remove_assistant(assistant)
        await self.space_repo.update(space)

        if icon_id:
            await self.icon_repo.delete(icon_id)

    async def get_prompts_by_assistant(self, assistant_id: UUID) -> list[Prompt]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_prompts_of_assistants():
            raise UnauthorizedException(
                "You do not have permission to read prompts for this assistant.",
                code="forbidden_action",
                context={
                    "resource_type": "prompt",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return await self.prompt_service.get_prompts_by_assistant(assistant_id)

    async def _handle_response(
        self,
        response: "CompletionModelResponse",
        datastore_result: "DatastoreResult",
        question: str,
        files: Sequence["File"],
        completion_model: "CompletionModel | CompletionModelPublic | None",
        session: "SessionInDB",
        stream: bool,
        assistant_id: UUID,
        question_id: UUID,
        skill_plan: SkillTurnPlan,
        skill_runtime: "SkillActivationRuntime",
        selected_model_route: str,
        initial_skill_context_tokens: int,
        version: int = 1,
        web_search_results: Sequence["WebSearchResult"] | None = None,
        assistant_selector_tokens: int = 0,
    ) -> str | AsyncGenerator[Completion, None]:
        # Capture tenant_id outside the generator so the abort-path background save
        # doesn't depend on self.user being safely accessible during teardown.
        tenant_id = self.user.tenant_id

        def _final_skill_runtime_state() -> tuple[
            tuple[SkillExecutionReference, ...],
            SkillActivationEvidenceV1,
        ]:
            assert completion_model is not None
            snapshot = skill_runtime.snapshot()
            return (
                skill_plan.active_provenance(snapshot),
                skill_plan.activation_evidence(
                    selected_model_id=completion_model.id,
                    selected_model_route=selected_model_route,
                    snapshot=snapshot,
                ),
            )

        if stream:

            async def response_stream() -> AsyncGenerator[Completion, None]:
                reasoning_token_count = 0
                response_string = ""
                reasoning_string = ""
                generated_files: list[File] = []
                tool_calls: list[ToolCallInfo] = []
                mcp_tool_references: list[McpToolReference] = []
                # TOOL_CALL chunks can fire twice in the approval flow. IDs
                # identify exact events without collapsing distinct resources
                # that legitimately share a URI.
                mcp_ref_seen: set[UUID] = set()
                stream_usage: TokenUsage | None = None
                stream_input_token_estimate: int | None = None
                completed = False

                try:
                    completion = response.completion
                    if isinstance(completion, str):
                        raise TypeError("Expected streaming completion response")

                    async for chunk in completion:
                        reasoning_token_count = chunk.reasoning_token_count
                        if chunk.usage:
                            stream_usage = chunk.usage
                        if chunk.input_token_estimate is not None:
                            stream_input_token_estimate = chunk.input_token_estimate

                        if chunk.response_type == ResponseType.TEXT:
                            response_string = f"{response_string}{chunk.text}"
                            chunk.reference_chunks = get_references(
                                response_string=response_string,
                                info_blobs=datastore_result.info_blobs,
                                version=version,
                            )
                            yield chunk

                        if chunk.response_type == ResponseType.REASONING:
                            # Reasoning/thinking text — pass through to SSE and
                            # accumulate separately so it can be persisted on the
                            # question without ever landing in the answer.
                            reasoning_string = (
                                f"{reasoning_string}{chunk.reasoning_content or ''}"
                            )
                            yield chunk

                        if chunk.response_type == ResponseType.FILES:
                            image_file = await self.file_service.save_image_from_bytes(
                                chunk.image_data
                            )

                            generated_files.append(image_file)
                            chunk.generated_file = image_file
                            yield chunk

                        if chunk.response_type == ResponseType.ENEO_EVENT:
                            yield chunk

                        if chunk.response_type == ResponseType.TOOL_CALL:
                            if chunk.mcp_tool_references:
                                for ref in chunk.mcp_tool_references:
                                    if ref.id in mcp_ref_seen:
                                        continue
                                    mcp_ref_seen.add(ref.id)
                                    mcp_tool_references.append(ref)
                            if chunk.tool_calls_metadata:
                                for tc in chunk.tool_calls_metadata:
                                    # Check if this tool_call already exists (from TOOL_APPROVAL_REQUIRED)
                                    existing = next(
                                        (
                                            t
                                            for t in tool_calls
                                            if t.tool_call_id
                                            and t.tool_call_id == tc.tool_call_id
                                        ),
                                        None,
                                    )
                                    if existing:
                                        # Update existing entry with approval status
                                        existing.approved = tc.approved
                                        existing.result_status = tc.result_status
                                        # Pending entries are emitted before the argument
                                        # JSON is complete; fill arguments in once a later
                                        # chunk carries them.
                                        if tc.arguments is not None:
                                            existing.arguments = cast(
                                                dict[str, object] | None,
                                                tc.arguments,
                                            )
                                        # The TOOL_CALL chunk after execution carries the
                                        # tool output; keep it so later turns can replay.
                                        if tc.result is not None:
                                            existing.result = tc.result
                                    else:
                                        # Add new tool call
                                        tool_calls.append(
                                            ToolCallInfo(
                                                server_name=tc.server_name,
                                                tool_name=tc.tool_name,
                                                title=tc.title,
                                                arguments=cast(
                                                    dict[str, object] | None,
                                                    tc.arguments,
                                                ),
                                                tool_call_id=tc.tool_call_id,
                                                approved=tc.approved,
                                                result_status=tc.result_status,
                                                result=tc.result,
                                                mcp_tool_name=tc.mcp_tool_name,
                                            )
                                        )
                            yield chunk

                        if chunk.response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
                            # Collect tool calls for approval flow (approval status will be updated later)
                            if chunk.tool_calls_metadata:
                                for tc in chunk.tool_calls_metadata:
                                    # A "pending" TOOL_CALL chunk may already have
                                    # registered this call — merge instead of
                                    # duplicating it.
                                    existing = next(
                                        (
                                            t
                                            for t in tool_calls
                                            if t.tool_call_id
                                            and t.tool_call_id == tc.tool_call_id
                                        ),
                                        None,
                                    )
                                    if existing:
                                        existing.approved = None
                                        existing.result_status = tc.result_status
                                        if tc.arguments is not None:
                                            existing.arguments = cast(
                                                dict[str, object] | None,
                                                tc.arguments,
                                            )
                                    else:
                                        tool_calls.append(
                                            ToolCallInfo(
                                                server_name=tc.server_name,
                                                tool_name=tc.tool_name,
                                                title=tc.title,
                                                arguments=cast(
                                                    dict[str, object] | None,
                                                    tc.arguments,
                                                ),
                                                tool_call_id=tc.tool_call_id,
                                                approved=None,
                                                result_status=tc.result_status,
                                                mcp_tool_name=tc.mcp_tool_name,
                                            )
                                        )
                            yield chunk

                        if chunk.response_type == ResponseType.TOOL_APPROVAL_TIMEOUT:
                            if chunk.tool_calls_metadata:
                                for tc in chunk.tool_calls_metadata:
                                    existing = next(
                                        (
                                            t
                                            for t in tool_calls
                                            if t.tool_call_id
                                            and t.tool_call_id == tc.tool_call_id
                                        ),
                                        None,
                                    )
                                    if existing:
                                        existing.approved = False
                                        existing.result_status = (
                                            tc.result_status or "timeout_denied"
                                        )
                                    else:
                                        tool_calls.append(
                                            ToolCallInfo(
                                                server_name=tc.server_name,
                                                tool_name=tc.tool_name,
                                                title=tc.title,
                                                arguments=cast(
                                                    dict[str, object] | None,
                                                    tc.arguments,
                                                ),
                                                tool_call_id=tc.tool_call_id,
                                                approved=False,
                                                result_status=tc.result_status
                                                or "timeout_denied",
                                                mcp_tool_name=tc.mcp_tool_name,
                                            )
                                        )
                            yield chunk

                    # Get the references for the whole response
                    reference_chunks = get_references(
                        response_string=response_string,
                        info_blobs=datastore_result.no_duplicate_chunks,
                        version=version,
                        get_id_func=lambda chunk: chunk.info_blob_id,
                    )
                    # Prefer actual provider token counts, fall back to litellm estimates
                    if stream_usage and stream_usage.prompt_tokens is not None:
                        num_tokens_question = (
                            stream_usage.prompt_tokens + assistant_selector_tokens
                        )
                        input_source = "provider"
                        assert completion_model is not None
                        log_token_count_drift(
                            model_name=completion_model.name,
                            predicted=response.total_token_count,
                            actual=stream_usage.prompt_tokens,
                        )
                    else:
                        final_skill_tokens = skill_runtime.snapshot().measurement.tokens
                        base_input_tokens = (
                            stream_input_token_estimate
                            if stream_input_token_estimate is not None
                            else response.total_token_count
                            + max(
                                final_skill_tokens - initial_skill_context_tokens,
                                0,
                            )
                        )
                        num_tokens_question = (
                            base_input_tokens + assistant_selector_tokens
                        )
                        input_source = "litellm"

                    if stream_usage and stream_usage.completion_tokens is not None:
                        num_tokens_answer = stream_usage.completion_tokens
                        output_source = "provider"
                    else:
                        assert completion_model is not None
                        num_tokens_answer = (
                            count_tokens(response_string, completion_model.name)
                            + reasoning_token_count
                        )
                        output_source = "litellm"

                    logger.info(
                        f"[TokenUsage] assistant={assistant_id} streaming — "
                        f"input={num_tokens_question} ({input_source}), "
                        f"output={num_tokens_answer} ({output_source})"
                    )

                    skill_provenance, skill_activation = _final_skill_runtime_state()
                    await self.session_service.complete_question_with_answer(
                        question_id=question_id,
                        answer=response_string,
                        num_tokens_question=num_tokens_question,
                        num_tokens_answer=num_tokens_answer,
                        completion_model=cast("AICompletionModel", completion_model),
                        info_blob_chunks=reference_chunks,
                        generated_files=generated_files,
                        logging_details=response.extended_logging
                        or LoggingDetails(model_kwargs={}),
                        web_search_results=list(web_search_results or []),
                        tool_calls=tool_calls if tool_calls else None,
                        mcp_tool_references=mcp_tool_references or None,
                        reasoning=reasoning_string or None,
                        skill_provenance=skill_provenance,
                        skill_activation=skill_activation,
                    )
                    completed = True

                    # Send token usage event to frontend
                    yield Completion(
                        text="",
                        response_type=ResponseType.TOKEN_USAGE,
                        usage=TokenUsage(
                            prompt_tokens=num_tokens_question,
                            completion_tokens=num_tokens_answer,
                        ),
                    )
                finally:
                    # Stream did not reach normal completion: client abort, LLM
                    # error, network drop, etc. The placeholder row already captures
                    # the user's question, so nothing streamed means there is
                    # nothing further to persist — skip the redundant UPDATE.
                    # Anything else (partial answer or reasoning streamed before
                    # abort) must be saved via a fresh DB session because the
                    # request-scoped AsyncSession may already be torn down and
                    # `await` across GeneratorExit is fragile.
                    if not completed and (
                        response_string
                        or reasoning_string
                        or skill_runtime.snapshot().changed
                    ):
                        from eneo.sessions.session_service import (
                            persist_partial_question_answer,
                            safe_count_tokens,
                            schedule_background_save,
                        )

                        model_name = (
                            completion_model.name
                            if completion_model is not None
                            else None
                        )
                        partial_tokens_answer = (
                            safe_count_tokens(response_string, model_name)
                            + reasoning_token_count
                        )
                        skill_provenance, skill_activation = (
                            _final_skill_runtime_state()
                        )
                        schedule_background_save(
                            persist_partial_question_answer(
                                tenant_id=tenant_id,
                                question_id=question_id,
                                answer=response_string,
                                num_tokens_answer=partial_tokens_answer,
                                reasoning=reasoning_string or None,
                                skill_provenance=skill_provenance,
                                skill_activation=skill_activation,
                            )
                        )
                        logger.info(
                            "Scheduled partial chat answer save on stream abort: "
                            f"assistant={assistant_id} question_id={question_id} "
                            f"answer_chars={len(response_string)}"
                        )

            return response_stream()
        else:
            reasoning_token_count = 0
            final_answer = ""
            final_reasoning: str | None = None
            generated_files: list[File] = []

            non_streaming_mcp_refs: list[McpToolReference] = []
            if response.completion is not None:
                answer = response.completion
                if isinstance(answer, str):
                    final_answer = answer
                else:
                    reasoning_token_count = getattr(answer, "reasoning_token_count", 0)
                    final_answer = getattr(answer, "text", "")
                    non_streaming_mcp_refs = (
                        getattr(answer, "mcp_tool_references", None) or []
                    )
                    final_reasoning = getattr(answer, "reasoning_content", None)

            reference_chunks = get_references(
                response_string=final_answer,
                info_blobs=datastore_result.no_duplicate_chunks,
                version=version,
                get_id_func=lambda chunk: chunk.info_blob_id,
            )
            # Prefer actual provider token counts, fall back to litellm estimates
            if response.usage and response.usage.prompt_tokens is not None:
                num_tokens_question = (
                    response.usage.prompt_tokens + assistant_selector_tokens
                )
                input_source = "provider"
            else:
                num_tokens_question = (
                    response.total_token_count + assistant_selector_tokens
                )
                input_source = "litellm"

            if response.usage and response.usage.completion_tokens is not None:
                num_tokens_answer = response.usage.completion_tokens
                output_source = "provider"
            else:
                assert completion_model is not None
                num_tokens_answer = (
                    count_tokens(final_answer, completion_model.name)
                    + reasoning_token_count
                )
                output_source = "litellm"

            logger.info(
                f"[TokenUsage] assistant={assistant_id} non-streaming — "
                f"input={num_tokens_question} ({input_source}), "
                f"output={num_tokens_answer} ({output_source})"
            )

            skill_provenance, skill_activation = _final_skill_runtime_state()
            await self.session_service.complete_question_with_answer(
                question_id=question_id,
                answer=final_answer,
                num_tokens_question=num_tokens_question,
                num_tokens_answer=num_tokens_answer,
                generated_files=generated_files,
                completion_model=cast("AICompletionModel", completion_model),
                info_blob_chunks=reference_chunks,
                logging_details=response.extended_logging
                or LoggingDetails(model_kwargs={}),
                web_search_results=list(web_search_results or []),
                mcp_tool_references=non_streaming_mcp_refs or None,
                reasoning=final_reasoning,
                skill_provenance=skill_provenance,
                skill_activation=skill_activation,
            )

            return final_answer

    async def _build_completion_file_inputs(
        self,
        files: list["File"],
        session: "SessionInDB",
        assistant: "Assistant",
        completion_model: Optional["CompletionModel"],
    ) -> AssistantCompletionFileInputs:
        """Build the file lists passed to the completion layer.

        Persistent attachments stay on ``assistant.attachments``. Rendered
        document images are a completion-side concern only: they are added to
        the message and prompt file inputs when the effective model has vision,
        but they are never persisted on the question or assistant.
        """
        if completion_model is None or not completion_model.vision:
            return AssistantCompletionFileInputs(
                completion_message_files=files,
                completion_prompt_files=assistant.attachments,
            )

        completion_prompt_files = await self._completion_prompt_files_for_model(
            persistent_attachments=assistant.attachments,
            completion_model=completion_model,
        )

        await self._attach_history_derivatives(session=session)

        return AssistantCompletionFileInputs(
            completion_message_files=await self.file_service.with_derived_images(files),
            completion_prompt_files=completion_prompt_files,
        )

    async def _attach_history_derivatives(self, session: "SessionInDB") -> None:
        """Re-attach derived images to history messages for replay.

        Derived images are not persisted on questions, so each ask rebuilds
        them in memory from the parent files referenced by the history.
        """
        parent_ids = {
            file.id
            for question in session.questions
            for file in question.files
            if file.file_type == FileType.TEXT
        }
        if not parent_ids:
            return

        derived = await self.file_service.get_derived_images(
            parent_ids=list(parent_ids)
        )
        if not derived:
            return

        by_parent: dict[UUID, list["File"]] = defaultdict(list)
        for image in derived:
            if image.parent_file_id is not None:
                by_parent[image.parent_file_id].append(image)

        for question in session.questions:
            present = {file.id for file in question.files}
            additions = [
                image
                for file in question.files
                if file.file_type == FileType.TEXT
                for image in by_parent.get(file.id, [])
                if image.id not in present
            ]
            if additions:
                question.files = list(question.files) + additions

    async def _check_assistant_models(self, assistant: "Assistant", space: "Space"):
        if assistant.completion_model is None:
            raise BadRequestException("Assistant has no completion model configured.")

        if not assistant.completion_model.can_access:
            raise UnauthorizedException(
                "Completion model is inaccessible, please contact your administrator"
            )
        elif not space.is_completion_model_in_space(assistant.completion_model.id):
            raise BadRequestException(
                f"Completion Model {assistant.completion_model.nickname} is not in space."
            )

        for item in assistant.collections + assistant.websites:
            if not space.is_embedding_model_in_space(item.embedding_model.id):
                raise BadRequestException(
                    f"Embedding Model {item.embedding_model.name} is not in space."
                )

    async def ask(
        self,
        question: str,
        assistant_id: "UUID",
        group_chat_id: Optional["UUID"] = None,
        session_id: "UUID | None" = None,
        file_ids: list["UUID"] | None = None,
        stream: bool = False,
        tool_assistant_id: Optional["UUID"] = None,
        version: int = 1,
        use_web_search: bool = False,
        assistant_selector_tokens: int = 0,
        require_tool_approval: bool = False,
        disabled_mcp_server_ids: list["UUID"] | None = None,
    ):
        # PRD §6 "Critical tests #2": defense-in-depth — never run a Help
        # Assistant via the normal ask path. Both ``POST /assistants/{id}/sessions/``
        # and ``POST /assistants/{id}/sessions/{session_id}/`` flow through
        # here, so guarding this method covers both router entry points and
        # short-circuits before any session row is created.
        await assert_not_helper_assistant(
            assistant_id=assistant_id,
            role_repo=self.org_space_assistant_role_repo,
            history_repo=self.help_assistant_assignment_history_repo,
        )
        if tool_assistant_id is not None:
            await assert_not_helper_assistant(
                assistant_id=tool_assistant_id,
                role_repo=self.org_space_assistant_role_repo,
                history_repo=self.help_assistant_assignment_history_repo,
            )

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        active_assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        # The personal chat is the personal space's default assistant — gated by
        # PERSONAL_CHAT (via can_read_default_assistant), not ASSISTANTS, so a
        # baseline role can chat without managing assistants.
        is_personal_default = (
            space.is_personal()
            and space.default_assistant is not None
            and active_assistant.id == space.default_assistant.id
        )
        can_use = (
            actor.can_read_default_assistant()
            if is_personal_default
            else actor.can_read_assistant(assistant=active_assistant)
        )
        if not can_use:
            raise UnauthorizedException(
                "You do not have permission to use this assistant.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "ask",
                    "auth_layer": "domain_policy",
                },
            )

        space.can_ask_assistant(assistant=active_assistant)

        if tool_assistant_id is not None:
            tool_assistant = space.get_assistant(assistant_id=tool_assistant_id)
            if tool_assistant_id not in [
                assistant.id for assistant in active_assistant.tool_assistants
            ]:
                raise BadRequestException()

            assistant_to_ask = tool_assistant
        else:
            assistant_to_ask = active_assistant

        cleaned_question = clean_eneo_tag(question)
        files = await self.file_service.get_files_by_ids(file_ids=file_ids or [])

        # Personal assistant governance runtime enforcement.
        # Resolve before creating a session/question placeholder so invalid
        # policy states fail without leaving empty conversation history behind.
        completion_model_override: "CompletionModel | None" = None
        mcp_servers_override: "list[MCPServer] | None" = None
        prompt_override: str | None = None
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant_to_ask
        )
        if effective_config is not None:
            if effective_config.models_enforced:
                # Same resolution preflight uses, so the projected and actual
                # models can't diverge. None here means the whitelist is empty.
                resolved_model = select_effective_completion_model(
                    current_model=assistant_to_ask.completion_model,
                    effective_config=effective_config,
                )
                if resolved_model is None:
                    raise BadRequestException(
                        "Personal assistant governance policy has no allowed models — "
                        "contact admin",
                    )
                # Only override when the policy steered away from the assistant's
                # own (stale) model; otherwise leave it untouched.
                if resolved_model is not assistant_to_ask.completion_model:
                    completion_model_override = resolved_model  # type: ignore[assignment]

            if effective_config.mcp_enforced:
                # GRANT semantics: the policy provides its allowed MCP servers to
                # the personal assistant directly. The user does not attach them
                # on the assistant (the entity's own mcp_servers stay empty), so
                # we hand the policy set straight to the completion call rather
                # than intersecting with assistant_to_ask.mcp_servers.
                mcp_servers_override = list(effective_config.available_mcp_servers)

            if (
                effective_config.prompt_enforced
                and effective_config.enforced_prompt_text
            ):
                prompt_override = effective_config.enforced_prompt_text

        effective_completion_model = (
            completion_model_override or assistant_to_ask.completion_model
        )
        if effective_completion_model is None:
            raise BadRequestException(
                "No completion model configured for this conversation.",
            )

        skill_plan = await self._create_skill_turn_plan(
            assistant=assistant_to_ask,
            effective_config=effective_config,
            space_is_personal=space.is_personal(),
        )
        model_route = effective_completion_model.get_model_route()
        skill_runtime = skill_plan.to_activation_runtime(
            selected_model_route=model_route,
            max_input_tokens=effective_completion_model.max_input_tokens,
            supports_tool_calling=effective_completion_model.supports_tool_calling,
        )
        initial_skill_snapshot = skill_runtime.snapshot()
        skill_composition = SkillComposition(
            prompt=skill_runtime.prompt,
            provenance=skill_plan.active_provenance(initial_skill_snapshot),
        )
        if skill_runtime.prompt != skill_plan.base_instructions:
            prompt_override = skill_runtime.prompt
        skill_activation = skill_plan.activation_evidence(
            selected_model_id=effective_completion_model.id,
            selected_model_route=model_route,
            snapshot=initial_skill_snapshot,
        )

        # Per-request MCP opt-out from the composer toolbar: narrow whatever set
        # is effective (policy-granted servers above, or the assistant's own) by
        # the servers the user switched off for this message. Narrowing only — it
        # can never enable a server that isn't already active.
        disabled_ids = set(disabled_mcp_server_ids or [])
        if disabled_ids:
            base_mcp_servers = (
                mcp_servers_override
                if mcp_servers_override is not None
                else list(assistant_to_ask.mcp_servers)
            )
            mcp_servers_override = [
                server for server in base_mcp_servers if server.id not in disabled_ids
            ]

        # This message's own uploads have no save-time fit gate and are inlined
        # whole, so reject an upload that can't fit before any session/question
        # row is created — same "fail before persisting" carve-out as governance.
        await self._assert_message_attachments_fit(
            assistant=assistant_to_ask,
            model=effective_completion_model,
            prompt_text=skill_composition.prompt,
            files=files,
            validate_persistent_baseline=bool(skill_composition.provenance)
            or bool(
                effective_config is not None
                and (
                    effective_config.models_enforced or effective_config.prompt_enforced
                )
            ),
        )

        question_id: UUID | None = None
        question_created_at: datetime | None = None
        is_new_session = session_id is None
        if not is_new_session:
            assert session_id is not None
            if group_chat_id is not None:
                session = await self.session_service.get_session_by_uuid(
                    id=session_id, group_chat_id=group_chat_id
                )
            else:
                session = await self.session_service.get_session_by_uuid(
                    id=session_id, assistant_id=assistant_id
                )
        else:
            # Set the name as the question or the filenames
            name = question
            if not name and files:
                name = " ".join(file.name for file in files)
            if group_chat_id is not None:
                (
                    session,
                    question_id,
                    question_created_at,
                ) = await self.session_service.create_session_with_question_placeholder(
                    name=name,
                    question=question,
                    files=files,
                    question_assistant_id=assistant_to_ask.id,
                    group_chat_id=group_chat_id,
                    completion_model=cast(
                        "AICompletionModel", effective_completion_model
                    ),
                    skill_provenance=skill_composition.provenance or None,
                    skill_activation=skill_activation,
                )
            else:
                (
                    session,
                    question_id,
                    question_created_at,
                ) = await self.session_service.create_session_with_question_placeholder(
                    name=name,
                    question=question,
                    files=files,
                    session_assistant_id=active_assistant.id,
                    question_assistant_id=assistant_to_ask.id,
                    completion_model=cast(
                        "AICompletionModel", effective_completion_model
                    ),
                    skill_provenance=skill_composition.provenance or None,
                    skill_activation=skill_activation,
                )

        assert session is not None
        for _question in session.questions:
            _question.question = clean_eneo_tag(_question.question)

        # `files` is what gets persisted on the question. The completion inputs
        # may additionally contain rendered document images that only the model sees.
        completion_file_inputs = await self._build_completion_file_inputs(
            files=files,
            session=session,
            assistant=assistant_to_ask,
            completion_model=effective_completion_model,
        )

        if not is_new_session:
            # Existing conversations need only the new placeholder transaction.
            (
                question_id,
                question_created_at,
            ) = await self.session_service.create_question_placeholder(
                question=question,
                session=session,
                files=files,
                assistant_id=assistant_to_ask.id,
                completion_model=cast("AICompletionModel", effective_completion_model),
                skill_provenance=skill_composition.provenance or None,
                skill_activation=skill_activation,
            )
        assert question_id is not None

        if use_web_search and version == 2:
            web_search = await self.web_search
            web_search_results = await web_search.search(search_query=question)
        else:
            web_search_results = []

        try:
            response, datastore_result = await assistant_to_ask.ask(
                question=cleaned_question,
                completion_service=self.completion_service,
                references_service=self.references_service,
                session=session,
                files=completion_file_inputs.completion_message_files,
                stream=stream,
                version=version,
                web_search_results=web_search_results,
                require_tool_approval=require_tool_approval,
                completion_model_override=completion_model_override,
                mcp_servers_override=mcp_servers_override,
                prompt_override=prompt_override,
                completion_prompt_files=completion_file_inputs.completion_prompt_files,
                skill_runtime=skill_runtime,
            )
        except Exception:
            failed_snapshot = skill_runtime.snapshot()
            if failed_snapshot.changed:
                try:
                    from eneo.sessions.session_service import (
                        persist_final_skill_runtime_state,
                    )

                    await persist_final_skill_runtime_state(
                        tenant_id=self.user.tenant_id,
                        question_id=question_id,
                        skill_provenance=skill_plan.active_provenance(failed_snapshot),
                        skill_activation=skill_plan.activation_evidence(
                            selected_model_id=effective_completion_model.id,
                            selected_model_route=model_route,
                            snapshot=failed_snapshot,
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Could not persist final Skill activation evidence after "
                        "completion failure"
                    )
            raise

        # TODO: Separate the response based on stream true or false

        answer = await self._handle_response(
            response=response,
            datastore_result=datastore_result,
            question=question,
            files=files,
            completion_model=effective_completion_model,
            session=session,
            stream=stream,
            assistant_id=assistant_to_ask.id,
            question_id=question_id,
            skill_plan=skill_plan,
            skill_runtime=skill_runtime,
            selected_model_route=model_route,
            initial_skill_context_tokens=(initial_skill_snapshot.measurement.tokens),
            version=version,
            web_search_results=web_search_results,
            assistant_selector_tokens=assistant_selector_tokens,
        )

        mcp_tool_references: list[McpToolReference] = []
        if not stream:
            assert isinstance(answer, str)
            info_blob_references = datastore_result.info_blobs
            if isinstance(response.completion, Completion):
                mcp_tool_references = response.completion.mcp_tool_references or []
        else:
            info_blob_references = datastore_result.info_blobs

        final_response = AssistantResponse(
            created_at=question_created_at,
            question=question,
            files=files,
            session=session,
            answer=answer,
            info_blobs=info_blob_references,
            completion_model=effective_completion_model,
            tools=UseTools(
                assistants=[
                    ToolAssistant(id=assistant_to_ask.id, handle=assistant_to_ask.name)
                ]
            ),
            description=assistant_to_ask.description,
            web_search_results=web_search_results,
            question_id=question_id,
            mcp_tool_references=mcp_tool_references,
        )

        return final_response

    async def publish_assistant(
        self, assistant_id: "UUID", publish: bool
    ) -> tuple[Assistant, list[ResourcePermission]]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_publish_assistants():
            raise UnauthorizedException(
                "Publishing assistants is not allowed for your current space role.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "publish",
                    "auth_layer": "domain_policy",
                },
            )

        if publish:
            await self._validate_attachments_fit(assistant, space=space)

        assistant.update(published=publish)

        await self.space_repo.update(space)

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    async def get_assistant_mcp_servers(self, assistant_id: UUID):
        """Get all MCP servers associated with an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_assistants():
            raise UnauthorizedException(
                "You do not have permission to read assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return assistant.mcp_servers

    async def add_mcp_to_assistant(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Add an MCP server to an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "edit_mcp",
                    "auth_layer": "domain_policy",
                },
            )

        # Get existing associations from the database
        import sqlalchemy as sa

        from eneo.database.tables.assistant_table import AssistantMCPServers
        from eneo.database.tables.mcp_server_table import (
            MCPServers as MCPServersTable,
        )

        # Validate tenant ownership + enablement
        mcp_server_query = sa.select(MCPServersTable).where(
            MCPServersTable.id == mcp_server_id,
            MCPServersTable.tenant_id == self.user.tenant_id,
            MCPServersTable.is_enabled == True,  # noqa: E712
        )
        mcp_server_db = await self.repo.session.scalar(mcp_server_query)
        if mcp_server_db is None:
            raise BadRequestException("MCP server is not enabled for this tenant")

        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )
        mcp_governed = effective_config is not None and effective_config.mcp_enforced
        if not mcp_governed and not space.is_mcp_server_in_space(mcp_server_id):
            # Validate against the space read model, not the stale
            # spaces_mcp_servers table (seeded once at space creation, never
            # back-filled), so a server enabled after a personal space was
            # created is assignable. See update_assistant (#500).
            raise BadRequestException(
                "MCP server is not assigned to this assistant's space"
            )

        await self._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=None,
            mcp_server_ids=[mcp_server_id],
            effective_config=effective_config,
        )

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_server_ids: list[UUID] = [
            row.mcp_server_id for row in result.scalars()
        ]

        # Check if already exists
        if mcp_server_id in existing_server_ids:
            raise BadRequestException("MCP server already associated with assistant")

        available_mcp_servers = (
            effective_config.available_mcp_servers
            if effective_config is not None and effective_config.mcp_enforced
            else space.mcp_servers
        )
        new_mcp_server = next(
            (server for server in available_mcp_servers if server.id == mcp_server_id),
            None,
        )
        if new_mcp_server is None:
            raise BadRequestException("MCP server is not available to this assistant")

        staged_mcp_servers = list(assistant.mcp_servers)
        staged_mcp_servers.append(new_mcp_server)
        projected_mcp_servers = await self.space_repo.project_assistant_mcp_servers(
            space_id=space.id,
            assistant_id=assistant_id,
            mcp_servers=staged_mcp_servers,
        )
        await self._validate_attachments_fit(
            assistant,
            space=space,
            validate_all_on_demand_candidates=True,
            mcp_servers_override=projected_mcp_servers,
        )

        # Persist only after the complete post-add provider payload is accepted.
        existing_server_ids.append(mcp_server_id)
        # Update via repository
        from eneo.database.tables.assistant_table import Assistants

        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)
        assert assistant_in_db is not None

        await self.repo.set_mcp_servers(assistant_in_db, existing_server_ids)
        # Keep the fit snapshot's parent-row version coupled to this association write.
        await self.repo.session.execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(updated_at=sa.func.now())
        )

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(
            assistant_id=assistant_id
        )
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    async def remove_mcp_from_assistant(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Remove an MCP server from an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "edit_mcp",
                    "auth_layer": "domain_policy",
                },
            )

        # Get existing associations from the database
        import sqlalchemy as sa

        from eneo.database.tables.assistant_table import (
            AssistantMCPServers,
            Assistants,
        )

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_server_ids: list[UUID] = [
            row.mcp_server_id for row in result.scalars()
        ]

        # Remove the association
        existing_server_ids = [
            server_id for server_id in existing_server_ids if server_id != mcp_server_id
        ]
        # Update via repository
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)
        assert assistant_in_db is not None

        await self.repo.set_mcp_servers(assistant_in_db, existing_server_ids)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(
            assistant_id=assistant_id
        )
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    async def update_assistant_mcp_config(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
        enabled: bool | None = None,
        config: dict[str, object] | None = None,
        priority: int | None = None,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Update the configuration of an MCP server association."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "edit_mcp",
                    "auth_layer": "domain_policy",
                },
            )

        # Get existing associations from the database
        import sqlalchemy as sa

        from eneo.database.tables.assistant_table import (
            AssistantMCPServers,
            Assistants,
        )

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_server_ids: list[UUID] = [
            row.mcp_server_id for row in result.scalars()
        ]

        # Check if the association exists
        if mcp_server_id not in existing_server_ids:
            raise BadRequestException("MCP server not associated with assistant")

        # Note: enabled/config/priority fields are not currently stored in the database schema
        # The association table only stores assistant_id and mcp_server_id
        # Update via repository
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)
        assert assistant_in_db is not None

        await self.repo.set_mcp_servers(assistant_in_db, existing_server_ids)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(
            assistant_id=assistant_id
        )
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions
