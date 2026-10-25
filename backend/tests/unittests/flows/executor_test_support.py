"""The flow executor and the records it reads, built for unit tests.

`build_flow_executor` runs whole flows from a published version;
`build_step_executor` runs single steps against a run's state.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec
from uuid import UUID, uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import AssistantOrigin
from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.completion_models.domain.model_kwargs_capabilities import SupportedModelKwargs
from eneo.completion_models.domain.request_preflight import (
    CompletionRequestPackage,
    CompletionRequestPreflight,
)
from eneo.files.file_models import FileType
from eneo.files.file_service import FileService
from eneo.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
)
from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.flow import (
    FlowVersion as FlowVersionModel,
)
from eneo.flows.domain.step_output import OUTPUT_TEXT_OVERFLOW_KEY
from eneo.flows.flow_input_limits import FlowInputLimits
from eneo.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from eneo.flows.runtime import executor as executor_module
from eneo.flows.runtime.executor import FlowRunExecutor, RuntimeStep
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.generated_file_names import GeneratedFileNames

_DEFAULT_SNAPSHOT_MODEL_ID = UUID("00000000-0000-0000-0000-000000000001")

DEFAULT_SNAPSHOT_PROMPT = "Execute this flow step."


@pytest.fixture(autouse=True)
def active_snapshot_provider(monkeypatch):
    monkeypatch.setattr(
        executor_module,
        "load_active_litellm_provider",
        AsyncMock(return_value=SimpleNamespace(id=UUID(int=2), provider_type="openai")),
    )


def flow_run(*, status: FlowRunStatus, user, input_payload=None) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=status,
        cancelled_at=None,
        input_payload_json=(
            input_payload if input_payload is not None else {"text": "hello"}
        ),
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def default_snapshot_assistant(assistant_id: UUID | str) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(str(assistant_id)),
        origin=AssistantOrigin.FLOW_MANAGED,
        prompt=SimpleNamespace(text=DEFAULT_SNAPSHOT_PROMPT, user_id=None),
        get_prompt_text=lambda: DEFAULT_SNAPSHOT_PROMPT,
        completion_model=SimpleNamespace(
            id=_DEFAULT_SNAPSHOT_MODEL_ID,
            name="gpt-5.4-nano",
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
            provider_id=UUID(int=2),
            provider_type="openai",
            get_model_route=lambda **_: "openai/gpt-5.4-nano",
            security_classification=None,
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
        attachments=[],
        inline_file_text=False,
        user=None,
        name="Assistant",
        logging_enabled=False,
    )


def _definition_step_with_default_snapshot(step: object) -> object:
    if not isinstance(step, dict):
        return step
    normalized = dict(step)
    if "assistant_snapshot" in normalized:
        return normalized
    assistant_id = normalized.get("assistant_id")
    if assistant_id is None:
        return normalized
    snapshot = build_assistant_execution_snapshot(
        assistant=default_snapshot_assistant(str(assistant_id)),
    )
    if snapshot is not None:
        normalized["assistant_snapshot"] = snapshot
    return normalized


def published_flow_version(
    *,
    flow_id: UUID,
    version: int,
    tenant_id: UUID,
    definition_checksum: str | None,
    definition_json: dict[str, object],
    created_at: datetime,
    updated_at: datetime,
) -> FlowVersionModel:
    """Complete a published fixture and derive its checksum by default."""
    if definition_checksum is None:
        if isinstance(definition_json.get("steps"), list):
            schema_version_provided = "schema_version" in definition_json
            steps = definition_json["steps"]
            if not schema_version_provided:
                steps = [_definition_step_with_default_snapshot(step) for step in steps]
            definition_json = {
                "schema_version": definition_json.get(
                    "schema_version", FLOW_DEFINITION_SCHEMA_VERSION
                ),
                "flow_id": definition_json.get("flow_id", str(flow_id)),
                "name": definition_json.get("name", "Test flow"),
                "description": definition_json.get("description"),
                "metadata_json": definition_json.get("metadata_json"),
                "steps": steps,
            }
        definition_checksum = canonical_json_hash(definition_json)
    return FlowVersionModel(
        flow_id=flow_id,
        version=version,
        tenant_id=tenant_id,
        definition_checksum=definition_checksum,
        definition_json=definition_json,
        created_at=created_at,
        updated_at=updated_at,
    )


def _started_step_attempt(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_id,
    step_order: int,
    attempt_no: int = 1,
) -> FlowStepAttempt:
    now = datetime.now(timezone.utc)
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step_id,
        step_order=step_order,
        attempt_no=attempt_no,
        predecessor_attempt_id=None,
        superseded_by_attempt_id=None,
        dispatch_task_id="task-1",
        status=FlowStepAttemptStatus.STARTED,
        error_code=None,
        requested_model=None,
        response_model=None,
        provider=None,
        finish_reason=None,
        provider_response_id=None,
        num_tokens_input=None,
        num_tokens_output=None,
        provenance_json=None,
        input_payload_json=None,
        output_payload_json=None,
        flow_step_execution_hash=None,
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )


def build_flow_executor(user, *, runtime_actor: FlowRunActor | None = None):
    flow_repo = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_repo.list_step_results.return_value = []
    # Finalization of a run without step results: completed, without an output.
    flow_run_repo.list_step_result_annotations.return_value = []
    flow_run_repo.read_last_completed_output_payload.return_value = None
    flow_version_repo = AsyncMock()
    flow_run_review_checkpoint_repo = AsyncMock()
    space_repo = AsyncMock()

    async def _create_or_get_attempt_started(**kwargs):
        return _started_step_attempt(
            run_id=kwargs["run_id"],
            flow_id=kwargs["flow_id"],
            tenant_id=kwargs["tenant_id"],
            step_id=kwargs["step_id"],
            step_order=kwargs["step_order"],
            attempt_no=kwargs["attempt_no"],
        )

    space = SimpleNamespace(
        id=uuid4(), tenant_id=user.tenant_id, security_classification=None
    )
    flow_repo.get.return_value = SimpleNamespace(space_id=space.id)
    space_repo.get_execution_space.return_value = space
    space_repo.get_execution_assistant.side_effect = (
        lambda *, space_id, assistant_id: default_snapshot_assistant(assistant_id)
    )
    model = default_snapshot_assistant(uuid4()).completion_model
    model.tenant_id = user.tenant_id
    space_repo.completion_model_repo.one.return_value = model

    flow_run_repo.allocate_next_attempt_no = AsyncMock(return_value=1)
    flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[])
    flow_run_repo.list_retained_input_file_ids = AsyncMock(
        side_effect=lambda **kwargs: list(
            flow_run_repo.list_step_input_file_ids.return_value
        )
    )
    flow_run_repo.create_or_get_attempt_started = AsyncMock(
        side_effect=_create_or_get_attempt_started
    )
    flow_run_repo.save_step_result = AsyncMock(
        side_effect=lambda _run_id, result, **_kwargs: result
    )

    async def _activate_step_attempt(**kwargs):
        attempt_input = kwargs["attempt_input"]
        return SimpleNamespace(
            input_payload_json=(
                attempt_input.to_payload() if attempt_input is not None else None
            )
        )

    flow_run_repo.activate_step_attempt = AsyncMock(side_effect=_activate_step_attempt)
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    file_content_loader = AsyncMock()
    file_service = create_autospec(FileService, instance=True)
    file_service.repo = file_repo
    file_repo.get_content_references.return_value = []

    async def owned_infos(*, file_ids):
        return [
            SimpleNamespace(
                id=file.id,
                size=file.size,
                name=getattr(file, "name", "source"),
                file_type=getattr(file, "file_type", "text"),
                mimetype=getattr(file, "mimetype", "text/plain"),
            )
            for file in file_service.get_files_by_ids.return_value
            if file.id in file_ids
        ]

    file_service.get_owned_file_infos.side_effect = owned_infos
    template_asset_repo = AsyncMock()
    encryption_service = AsyncMock()
    flow_run_terminalizer = SimpleNamespace()

    async def _terminalize_run(**kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status=kwargs["target_status"]),
            did_transition=True,
            target_status=kwargs["target_status"],
            source=kwargs["source"],
            audit_outbox_id=uuid4(),
        )

    flow_run_terminalizer.terminalize_run = AsyncMock(side_effect=_terminalize_run)
    executor = FlowRunExecutor(
        # The worker opens this on a session of its own; here the executor's audit service serves.
        read_audit_service=lambda: nullcontext(executor.audit_service),
        runtime_actor=runtime_actor or FlowRunActor.from_user(user=user),
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=flow_run_review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        file_content_loader=file_content_loader,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
        encryption_service=encryption_service,
        flow_run_terminalizer=flow_run_terminalizer,
        max_inline_text_bytes=1024 * 1024,
        input_limits=FlowInputLimits(
            file_max_size_bytes=100_000_000, audio_max_size_bytes=100_000_000
        ),
    )
    # What execute_claimed derives from the pinned definition before any step.
    executor.generated_file_names = GeneratedFileNames.for_run(
        flow_name="Nämndmöte",
        steps=(),
        run_created_at=datetime(2026, 9, 23, 12, tzinfo=timezone.utc),
    )
    return executor, flow_repo, flow_run_repo, flow_version_repo


def build_step_executor(
    user,
    *,
    max_inline_text_bytes: int = 1024 * 1024,
    invocation_deadline: float | None = None,
):
    flow_repo = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[])
    flow_run_repo.list_retained_input_file_ids = AsyncMock(
        side_effect=lambda **kwargs: list(
            flow_run_repo.list_step_input_file_ids.return_value
        )
    )
    flow_run_repo.list_step_results.return_value = []
    # Finalization of a run without step results: completed, without an output.
    flow_run_repo.list_step_result_annotations.return_value = []
    flow_run_repo.read_last_completed_output_payload.return_value = None

    async def _activate_step_attempt(**kwargs):
        attempt_input = kwargs["attempt_input"]
        return SimpleNamespace(
            input_payload_json=(
                attempt_input.to_payload() if attempt_input is not None else None
            )
        )

    flow_run_repo.activate_step_attempt = AsyncMock(side_effect=_activate_step_attempt)
    flow_run_repo.write_attempt_tool_call_evidence = AsyncMock(return_value="written")
    flow_version_repo = AsyncMock()
    flow_run_review_checkpoint_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    file_repo.get_content_references.return_value = []
    file_content_loader = AsyncMock()
    file_service = create_autospec(FileService, instance=True)
    file_service.repo = file_repo

    async def owned_infos(*, file_ids):
        content = file_service.get_files_by_ids
        if callable(content.side_effect):
            files = await content.side_effect(file_ids=file_ids)
        elif isinstance(content.side_effect, BaseException):
            files = [SimpleNamespace(id=file_id) for file_id in file_ids]
        else:
            files = content.return_value
        return [
            SimpleNamespace(
                id=file.id,
                name=getattr(file, "name", "source"),
                mimetype=getattr(file, "mimetype", "text/plain"),
                file_type=getattr(file, "file_type", FileType.TEXT),
                size=getattr(file, "size", 0),
            )
            for file in files
        ]

    file_service.get_owned_file_infos.side_effect = owned_infos
    template_asset_repo = AsyncMock()
    encryption_service = AsyncMock()
    flow_run_terminalizer = SimpleNamespace()

    async def _terminalize_run(**kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status=kwargs["target_status"]),
            did_transition=True,
            target_status=kwargs["target_status"],
            source=kwargs["source"],
            audit_outbox_id=uuid4(),
        )

    flow_run_terminalizer.terminalize_run = AsyncMock(side_effect=_terminalize_run)
    executor = FlowRunExecutor(
        # The worker opens this on a session of its own; here the executor's audit service serves.
        read_audit_service=lambda: nullcontext(executor.audit_service),
        runtime_actor=FlowRunActor.from_user(user=user),
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=flow_run_review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        file_content_loader=file_content_loader,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
        encryption_service=encryption_service,
        flow_run_terminalizer=flow_run_terminalizer,
        max_inline_text_bytes=max_inline_text_bytes,
        invocation_deadline=invocation_deadline,
        input_limits=FlowInputLimits(
            file_max_size_bytes=100_000_000, audio_max_size_bytes=100_000_000
        ),
    )
    # What execute_claimed derives from the pinned definition before any step.
    executor.generated_file_names = GeneratedFileNames.for_run(
        flow_name="Nämndmöte",
        steps=(),
        run_created_at=datetime(2026, 9, 23, 12, tzinfo=timezone.utc),
    )
    return executor, flow_repo, flow_run_repo, flow_version_repo


def runtime_step(
    *,
    step_order: int = 1,
    input_source: str = "flow_input",
    input_type: str = "text",
    input_contract: dict | None = None,
    output_type: str = "text",
    output_contract: dict | None = None,
    input_bindings: dict | None = None,
    input_config: dict | None = None,
    output_mode: str = "pass_through",
    output_config: dict | None = None,
) -> RuntimeStep:
    if input_config is None and input_type in {"document", "file"}:
        input_config = {"runtime_input": {"enabled": True, "input_format": "document"}}
    if input_config is None and input_type == "audio":
        input_config = {"runtime_input": {"enabled": True, "input_format": "audio"}}
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=input_config,
        output_mode=output_mode,
        output_config=output_config,
        output_type=output_type,
        output_contract=output_contract,
        input_type=input_type,
        input_contract=input_contract,
    )


def completed_step_result(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_order: int,
    text: str,
    structured: dict | list | None = None,
    text_overflow: dict | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {"text": text}
    if structured is not None:
        payload["structured"] = structured
    if text_overflow is not None:
        payload[OUTPUT_TEXT_OVERFLOW_KEY] = text_overflow
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        current_attempt_no=1,
        input_payload_json={"text": f"input-{step_order}"},
        effective_prompt="prompt",
        output_payload_json=payload,
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


def context_preflight(token_count: int) -> CompletionRequestPreflight:
    from eneo.tokens.token_utils import TokenCount, TokenCountSource

    package = CompletionRequestPackage(
        messages=[],
        tools=[],
        response_format=None,
        input_reserve=TokenCount(tokens=token_count, source=TokenCountSource.LITELLM),
        useful_output_reserve_tokens=256,
        output_cap_tokens=4000,
    )
    return CompletionRequestPreflight(
        model_route="test/model",
        capacity=ModelCapacity(100_000, 4000),
        retrieval_included=False,
        preferred=package,
        fallback=replace(package),
    )


def mock_assistant_for_execute_step(*, response_text: str = "ok") -> MagicMock:
    assistant = MagicMock()
    assistant.mcp_servers = []
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = ModelKwargs()
    assistant.completion_model = SimpleNamespace(
        id=uuid4(),
        name="test",
        provider_type="test",
        litellm_model_name=None,
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            completion=response_text,
            total_token_count=3,
        )
    )
    assistant.preflight_response_context = AsyncMock(return_value=context_preflight(1))
    return assistant


def completed_grounded_result(
    *,
    step_order: int,
    source_id: str = "11111111-1111-1111-1111-111111111111",
    rag: dict[str, object] | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={
            "rag": rag
            if rag is not None
            else {
                "status": "success",
                "tracking": {
                    "retrieval_tracked": True,
                    "prompt_context_inclusion_tracked": True,
                    "citation_tracked": False,
                    "material_influence_tracked": False,
                },
                "prompt_context": {
                    "tracked": True,
                    "included_source_ids": [source_id],
                    "included_source_titles": ["Procurement memo"],
                    "included_groups": [
                        {
                            "source_id": source_id,
                            "source_id_short": source_id[:8],
                            "source_title": "Procurement memo",
                            "chunk_count": 1,
                        }
                    ],
                },
                "citation_sources": [
                    {
                        "id": source_id,
                        "id_short": source_id[:8],
                        "title": "Procurement memo",
                        "source_title": "Procurement memo",
                        "source_display_name": "Procurement memo",
                    }
                ],
                "passage_evidence_location": "attempt_provenance",
            }
        },
        effective_prompt=None,
        output_payload_json={"text": "Grounded summary"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )
