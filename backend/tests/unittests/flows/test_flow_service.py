from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant, AssistantOrigin
from eneo.assistants.assistant_update import (
    AssistantUpdateCaller,
    AssistantUpdateCommand,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import Flow, FlowStep, FlowVersion
from eneo.flows.domain.flow_invariant_exceptions import (
    FlowPersistedIdMissingError,
    FlowPublishedDefinitionInvalidError,
)
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
)
from eneo.flows.enums import FlowInputSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.http_transport import SECRET_SENTINEL
from eneo.flows.variable_resolver import iter_template_expressions
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED
from eneo.prompts.api.prompt_models import PromptCreate


class _FakeEncryptionService:
    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith("enc:")

    def can_decrypt(self, value: str) -> bool:
        return value.startswith("enc:")

    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")


class _OpaqueEncryptionService(_FakeEncryptionService):
    """Ciphertext that shows nothing of the plaintext, as real ciphertext does."""

    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext[::-1]}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")[::-1]


class _InactiveEncryptionService:
    """Deployment without ENCRYPTION_KEY: ciphertext is still recognizable."""

    def is_active(self) -> bool:
        return False

    def is_encrypted(self, value: str) -> bool:
        return value.startswith("enc:")

    def can_decrypt(self, value: str) -> bool:
        return False  # No key: nothing can be authenticated.

    def encrypt(self, plaintext: str) -> str:
        raise AssertionError("should not be called")

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")


def _step(step_order: int = 1) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
    )


def _ai_builder_origin_metadata() -> dict[str, str]:
    return {
        "builder_session_id": str(uuid4()),
        "builder_plan_id": str(uuid4()),
        "builder_spec_hash": "spec-hash",
        "applied_at": "2026-07-01T12:00:00+00:00",
    }


def _http_authored_config(secret_value: str | dict[str, str]):
    return {
        "url": "https://example.org/output",
        "auth": {"mode": "none"},
        "custom_headers": [
            {"name": "X-Step-Secret", "value": secret_value, "secret": True}
        ],
    }


def _build_assistant(*, flow_id, space_id, user) -> Assistant:
    return Assistant(
        id=uuid4(),
        user=user,
        space_id=space_id,
        completion_model=None,
        name="Flow managed",
        prompt=None,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[],
        published=False,
        hidden=True,
        origin=AssistantOrigin.FLOW_MANAGED,
        managing_flow_id=flow_id,
    )


def _classification(level: int):
    return SimpleNamespace(security_level=level)


class _FlowSecuritySpaceStub:
    def __init__(self, *, level: int | None = None, completion_models=None):
        self.security_classification = (
            _classification(level) if level is not None else None
        )
        self._completion_models = {
            model.id: model for model in (completion_models or [])
        }

    def get_completion_model(self, model_id):
        return self._completion_models[model_id]


def _stub_template_asset_lookup(
    service: FlowService,
    *,
    flow_id,
    file_id,
    asset_id=None,
    checksum: str = "abc123",
    name: str = "rapport.docx",
    placeholder_names: tuple[str, ...] = ("section",),
):
    resolved_asset_id = asset_id or uuid4()
    asset = SimpleNamespace(
        id=resolved_asset_id,
        flow_id=flow_id,
        file_id=file_id,
        name="old-template.docx",
        checksum="old-checksum",
    )
    file = SimpleNamespace(
        id=file_id,
        checksum=checksum,
        name=name,
        tenant_id=service.user.tenant_id,
    )
    service.template_asset_service.get_asset_for_publication.return_value = (
        asset,
        file,
        placeholder_names,
    )
    return asset


def _service(
    *,
    user,
    flow_repo,
    version_repo,
    encryption_service=None,
    space_service=None,
    stub_assistant_scope: bool = True,
) -> FlowService:
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        encryption_service=encryption_service,
        space_service=space_service,
    )
    if stub_assistant_scope:
        service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    service.assistant_service.get_assistant.side_effect = lambda assistant_id: (
        Assistant(
            id=assistant_id,
            user=None,
            space_id=uuid4(),
            completion_model=None,
            name="Assistant",
            prompt=None,
            completion_model_kwargs=ModelKwargs(),
            logging_enabled=False,
            websites=[],
            collections=[],
            attachments=[],
            published=False,
        ),
        [],
    )
    return service


@pytest.mark.asyncio
async def test_template_file_reference_requires_persisted_flow_id(user) -> None:
    service = _service(
        user=user,
        flow_repo=AsyncMock(),
        version_repo=AsyncMock(),
    )
    template_asset_id = uuid4()
    step = _step(step_order=1).model_copy(
        update={
            "output_mode": "template_fill",
            "output_type": "docx",
            "output_config": {"template_asset_id": str(template_asset_id)},
        }
    )
    flow = Flow(
        id=None,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Template flow",
        steps=[step],
    )

    with pytest.raises(FlowPersistedIdMissingError):
        await service._resolve_template_asset_reference(step=step, flow=flow)

    service.template_asset_service.get_asset_for_publication.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_flows_passes_space_visibility_to_the_tenant_repo_path(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.get_sparse_by_spaces.return_value = []
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    space_ids = [uuid4(), uuid4()]

    await service.list_flows(
        space_ids=space_ids,
        draft_space_ids=space_ids[:1],
        limit=25,
        offset=10,
    )

    flow_repo.get_sparse_by_spaces.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        space_ids=space_ids,
        draft_space_ids=space_ids[:1],
        limit=25,
        offset=10,
    )


@pytest.mark.asyncio
async def test_replace_resource_bindings_uses_current_user_tenant(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    flow_id = uuid4()
    binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="default-model",
            label="Default model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )

    await service.replace_resource_bindings(
        flow_id=flow_id,
        bindings=(binding,),
        source=FlowResourceBindingSource.AI_BUILDER,
    )

    flow_repo.replace_resource_bindings.assert_awaited_once_with(
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        bindings=(binding,),
        source=FlowResourceBindingSource.AI_BUILDER,
    )


@pytest.mark.asyncio
async def test_list_resource_bindings_uses_current_user_tenant(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    flow_id = uuid4()
    flow_repo.list_resource_bindings.return_value = tuple()

    bindings = await service.list_resource_bindings(flow_id=flow_id)

    assert bindings == tuple()
    flow_repo.list_resource_bindings.assert_awaited_once_with(
        flow_id=flow_id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_create_flow_rejects_invalid_form_schema(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={"form_schema": {"fields": "not-a-list"}},
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_invalid_care_data_policy(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(
        BadRequestException,
        match="metadata_json.care_data_policy.pre_approval_visibility",
    ):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={
                "care_data_policy": {
                    "sensitive": True,
                    "pre_approval_visibility": "everyone",
                }
            },
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_duplicate_step_order(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step_one = _step(step_order=1)
    step_duplicate = _step(step_order=1)

    with pytest.raises(BadRequestException, match="Duplicate step_order"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step_one, step_duplicate],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_non_contiguous_step_order(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException, match="contiguous and start at 1"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step(step_order=1), _step(step_order=3)],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_publish_flow_creates_version_and_updates_published_version(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    space_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=space_id,
        name="Publishable Flow",
        description="Test flow",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=7,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1), _step(step_order=2)],
    )
    created_version = FlowVersion(
        flow_id=flow_id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={"dummy": True},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    updated_flow = source_flow.model_copy(update={"published_version": 1})

    flow_repo.get.return_value = source_flow
    flow_repo.allocate_next_version.return_value = 1
    version_repo.create.return_value = created_version
    flow_repo.update.return_value = updated_flow

    result = await service.publish_flow(flow_id=flow_id)

    assert result.published_version == 1
    assert version_repo.create.await_args.kwargs["source_draft_revision"] == 7
    assert (
        version_repo.create.await_args.kwargs["first_published_at"].tzinfo is not None
    )
    version_repo.create.assert_awaited_once()
    flow_repo.update.assert_awaited_once()
    assert flow_repo.update.await_args.kwargs["expected_revision"] == 7


@pytest.mark.asyncio
async def test_publish_flow_snapshots_the_assistants_it_validated(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    section_step = _step(step_order=2).model_copy(
        update={
            "input_bindings": {"question": "{{ flow_input.text }}"},
            "input_config": {"text_processing": {"mode": "process_each_section"}},
            "output_contract": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"note": {"type": "string"}},
                        },
                    }
                },
            },
        }
    )
    fetches: dict[object, int] = {}

    def edited_after_first_read(assistant_id):
        # A second read would see an edit made after validation: a prompt
        # selecting the JSON step's output, which publish refuses.
        fetches[assistant_id] = fetches.get(assistant_id, 0) + 1
        prompt = (
            "Sammanfatta." if fetches[assistant_id] == 1 else "{{ step_1.output.text }}"
        )
        return (
            Assistant(
                id=assistant_id,
                user=None,
                space_id=uuid4(),
                completion_model=None,
                name="Assistant",
                prompt=SimpleNamespace(text=prompt),
                completion_model_kwargs=ModelKwargs(),
                logging_enabled=False,
                websites=[],
                collections=[],
                attachments=[],
                published=False,
            ),
            [],
        )

    service.assistant_service.get_assistant.side_effect = edited_after_first_read
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Sectioned Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1), section_step],
    )
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1

    await service.publish_flow(flow_id=flow.id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert [
        step["assistant_snapshot"]["instructions"] for step in definition["steps"]
    ] == ["Sammanfatta.", "Sammanfatta."]
    assert set(fetches.values()) == {1}


@pytest.mark.asyncio
async def test_publish_flow_refuses_section_step_reading_json_step_text(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    section_step = _step(step_order=2).model_copy(
        update={
            "input_bindings": {"question": "{{ step_1.output.text }}"},
            "input_config": {"text_processing": {"mode": "process_each_section"}},
            "output_contract": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"note": {"type": "string"}},
                        },
                    }
                },
            },
        }
    )
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Sectioned Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1), section_step],
    )
    flow_repo.get.return_value = flow

    with pytest.raises(FlowStepValidationError) as caught:
        await service.publish_flow(flow_id=flow.id)

    assert caught.value.code == (
        FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assert caught.value.step_order == 2
    assert caught.value.context["reference"] == "step_1.output.text"
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "prompt", "field", "reference"),
    [
        pytest.param(
            "{{ föregående_steg }}",
            "",
            "input_bindings.question",
            "föregående_steg",
            id="previous-step-alias",
        ),
        pytest.param(
            "{{ flow_input.text }}",
            "Notera {{ step_1.output.text }}",
            "prompt",
            "step_1.output.text",
            id="assistant-prompt",
        ),
    ],
)
async def test_publish_flow_refuses_section_step_selecting_json_step(
    user, question, prompt, field, reference
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    section_step = _step(step_order=2).model_copy(
        update={
            "input_bindings": {"question": question},
            "input_config": {"text_processing": {"mode": "process_each_section"}},
            "output_contract": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"note": {"type": "string"}},
                        },
                    }
                },
            },
        }
    )
    prompts = {section_step.assistant_id: prompt}
    service.assistant_service.get_assistant.side_effect = lambda assistant_id: (
        Assistant(
            id=assistant_id,
            user=None,
            space_id=uuid4(),
            completion_model=None,
            name="Assistant",
            prompt=SimpleNamespace(text=prompts.get(assistant_id, "")),
            completion_model_kwargs=ModelKwargs(),
            logging_enabled=False,
            websites=[],
            collections=[],
            attachments=[],
            published=False,
        ),
        [],
    )
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Sectioned Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1), section_step],
    )
    flow_repo.get.return_value = flow

    with pytest.raises(FlowStepValidationError) as caught:
        await service.publish_flow(flow_id=flow.id)

    assert caught.value.code == (
        FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assert caught.value.step_order == 2
    assert caught.value.context["field"] == field
    assert caught.value.context["reference"] == reference
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


_FORM_ONLY_RUN = {"form_schema": {"fields": [{"name": "diarienummer", "type": "text"}]}}
_UPLOAD_RUN_CONFIG = {
    "runtime_input": {"enabled": True, "input_format": "document", "required": True}
}


def _run_input_flow(user, *, metadata_json, steps):
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Run input flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=metadata_json,
        data_retention_days=None,
        draft_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=steps,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata_json", "first_step", "prompt", "field", "reference"),
    [
        pytest.param(
            _FORM_ONLY_RUN,
            {
                "input_bindings": {
                    "question": "{{ indata_text }}\n\n"
                    "diarienummer: {{ flow_input.diarienummer }}"
                }
            },
            "",
            "input_bindings.question",
            "indata_text",
            id="form-run-question-reads-text",
        ),
        pytest.param(
            _FORM_ONLY_RUN,
            {"input_bindings": {"question": "{{ flow_input.diarienummer }}"}},
            "Sammanfatta {{ indata_text }}.",
            "prompt",
            "indata_text",
            id="form-run-prompt-reads-text",
        ),
        pytest.param(
            _FORM_ONLY_RUN,
            {"input_bindings": {"question": "{{ indata_json.rader }}"}},
            "",
            "input_bindings.question",
            "indata_json.rader",
            id="form-run-question-reads-json",
        ),
        pytest.param(
            _FORM_ONLY_RUN,
            {"input_bindings": {"question": "{{ flow_input.text }}"}},
            "",
            "input_bindings.question",
            "flow_input.text",
            id="form-run-question-reads-payload-text",
        ),
        pytest.param(
            _FORM_ONLY_RUN,
            {"input_bindings": {"question": "{{ flow_input.diarienummer }}"}},
            "Läs {{ flow.input.structured.rader }}.",
            "prompt",
            "flow.input.structured.rader",
            id="form-run-prompt-reads-payload-structured",
        ),
        pytest.param(
            None,
            {"input_type": "document", "input_config": _UPLOAD_RUN_CONFIG},
            "Sammanfatta {{ indata_text }}.",
            "prompt",
            "indata_text",
            id="upload-run-prompt-reads-text",
        ),
    ],
)
async def test_publish_flow_refuses_a_read_of_run_text_the_run_never_collects(
    user, metadata_json, first_step, prompt, field, reference
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(update=first_step)
    prompts = {step.assistant_id: prompt}
    service.assistant_service.get_assistant.side_effect = lambda assistant_id: (
        Assistant(
            id=assistant_id,
            user=None,
            space_id=uuid4(),
            completion_model=None,
            name="Assistant",
            prompt=SimpleNamespace(text=prompts.get(assistant_id, "")),
            completion_model_kwargs=ModelKwargs(),
            logging_enabled=False,
            websites=[],
            collections=[],
            attachments=[],
            published=False,
        ),
        [],
    )
    flow = _run_input_flow(user, metadata_json=metadata_json, steps=[step])
    flow_repo.get.return_value = flow

    with pytest.raises(FlowStepValidationError) as caught:
        await service.publish_flow(flow_id=flow.id)

    assert caught.value.code == FlowGraphIssueCode.FLOW_INPUT_ALIAS_NOT_RECEIVED.value
    assert caught.value.step_order == 1
    assert caught.value.context["field"] == field
    assert caught.value.context["reference"] == reference
    assert reference.split(".")[0] in str(caught.value)
    assert "flow_input." in str(caught.value) or "step_input.text" in str(caught.value)
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata_json", "question"),
    [
        pytest.param(None, "{{ indata_text }}", id="free-text-run-reads-text"),
        pytest.param(None, "{{ indata_json.rader }}", id="free-text-run-reads-json"),
        pytest.param(None, "{{ flow_input.text }}", id="free-text-run-reads-payload"),
        pytest.param(
            _FORM_ONLY_RUN,
            "diarienummer: {{ flow_input.diarienummer }}",
            id="form-run-reads-its-field",
        ),
    ],
)
async def test_publish_flow_accepts_reads_the_run_collects(
    user, metadata_json, question
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={"input_bindings": {"question": question}}
    )
    flow = _run_input_flow(user, metadata_json=metadata_json, steps=[step])
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})

    await service.publish_flow(flow_id=flow.id)

    version_repo.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "binding", ["missing", "missing_id", "missing_type", "provider_backed"]
)
async def test_publish_flow_requires_provider_binding(user, binding):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step()
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Publishable flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[step],
    )
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})
    assistant, _ = await service.assistant_service.get_assistant(step.assistant_id)
    assistant.completion_model = SimpleNamespace(
        id=uuid4(),
        tenant_id=None,
        can_access=True,
        provider_id=uuid4() if binding in {"missing_type", "provider_backed"} else None,
        provider_type="openai"
        if binding in {"missing_id", "provider_backed"}
        else None,
        get_model_route=lambda: "openai/model-a",
        security_classification=None,
    )
    service.assistant_service.get_assistant.side_effect = None
    service.assistant_service.get_assistant.return_value = (assistant, [])

    if binding == "provider_backed":
        result = await service.publish_flow(flow_id=flow.id)
        assert result.published_version == 1
        version_repo.create.assert_awaited_once()
        snapshot = version_repo.create.await_args.kwargs["definition_json"]["steps"][0][
            "assistant_snapshot"
        ]
        assert snapshot["schema_version"] == 2
        assert snapshot["completion_model"]["provider_id"] == str(
            assistant.completion_model.provider_id
        )
    else:
        with pytest.raises(FlowStepValidationError) as caught:
            await service.publish_flow(flow_id=flow.id)
        assert caught.value.code == "flow_assistant_model_provider_required"
        assert caught.value.step_order == step.step_order
        assert "Select a provider-backed model" in str(caught.value)
        version_repo.create.assert_not_awaited()
        flow_repo.lock_publication_pointer.assert_not_awaited()
        flow_repo.allocate_next_version.assert_not_awaited()
        flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_flow_rejects_snapshot_missing_stable_step_id(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Publishable Flow",
        description="Test flow",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=7,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1).model_copy(update={"id": None})],
    )

    flow_repo.get.return_value = source_flow
    flow_repo.allocate_next_version.return_value = 1

    with pytest.raises(FlowPublishedDefinitionInvalidError) as exc_info:
        await service.publish_flow(flow_id=flow_id)

    assert exc_info.value.flow_id == flow_id
    assert exc_info.value.flow_version == 1
    assert exc_info.value.parser_code == "flow_version_missing_step_identifiers"
    assert exc_info.value.parser_context == {"step_order": 1}
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_flow_rejects_legacy_http_post_input_before_version_work(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Legacy POST input",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step().model_copy(
                update={
                    "input_source": "http_post",
                    "input_config": {
                        "url": "https://example.org/mutate",
                        "auth": {"mode": "none"},
                    },
                }
            )
        ],
    )
    flow_repo.get.return_value = source_flow

    with pytest.raises(
        BadRequestException, match="unsupported input_source 'http_post'"
    ):
        await service.publish_flow(flow_id=flow_id)

    version_repo.get_latest.assert_not_awaited()
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_unpublish_flow_updates_with_expected_revision(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Published Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=2,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=9,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = flow
    flow_repo.update.side_effect = lambda flow, **_: flow

    result = await service.unpublish_flow(flow_id=flow_id)

    assert result.published_version is None
    assert flow_repo.update.await_args.kwargs["expected_revision"] == 9


@pytest.mark.asyncio
async def test_publish_flow_uses_normalized_metadata_in_snapshot(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    builder_origin = _ai_builder_origin_metadata()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Publishable Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json={
            "form_schema": {
                "fields": [{"name": "case_id", "type": "string"}],
            },
            "care_data_policy": {},
            "ai_builder": {
                "origin": builder_origin,
                "description": "Generated draft",
            },
        },
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["metadata_json"] == {
        "form_schema": {"fields": [{"name": "case_id", "type": "text"}]},
        "care_data_policy": {"sensitive": False},
        "ai_builder": {"origin": builder_origin},
    }
    assert "definition_checksum" not in version_repo.create.await_args.kwargs


@pytest.mark.asyncio
async def test_publish_flow_omits_default_review_expiry_from_definition(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    review_step = _step(step_order=1).model_copy(
        update={
            "review_policy": FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW),
        }
    )
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Review Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[review_step],
    )
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["steps"][0]["review_policy"] == {"mode": "view"}


@pytest.mark.asyncio
async def test_publish_flow_rejects_mcp_assistant_before_version_creation(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    step = _step(step_order=1)
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="MCP flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[step],
    )
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})
    service.assistant_service.get_assistant.side_effect = None
    service.assistant_service.get_assistant.return_value = (
        SimpleNamespace(
            id=step.assistant_id,
            origin=AssistantOrigin.FLOW_MANAGED,
            managing_flow_id=flow_id,
            prompt=SimpleNamespace(text="Use the weather tool only when needed."),
            get_prompt_text=lambda: "Use the weather tool only when needed.",
            completion_model=None,
            completion_model_kwargs=ModelKwargs(),
            collections=[],
            websites=[],
            integration_knowledge_list=[],
            mcp_servers=[
                SimpleNamespace(
                    id=uuid4(),
                    name="Weather Server",
                    tools=[
                        SimpleNamespace(
                            id=uuid4(),
                            name="forecast_tool",
                            is_enabled=True,
                        ),
                        SimpleNamespace(
                            id=uuid4(), name="history_tool", is_enabled=False
                        ),
                    ],
                )
            ],
        ),
        [],
    )

    with pytest.raises(BadRequestException, match="Flow MCP is unsupported"):
        await service.publish_flow(flow_id=flow_id)

    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_passes_expected_revision_to_repo(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        draft_revision=3,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = existing
    flow_repo.update.return_value = existing

    await service.update_flow(
        flow_id=flow_id,
        name="Updated",
        expected_revision=3,
    )

    flow_repo.update.assert_awaited_once()
    assert flow_repo.update.await_args.kwargs["expected_revision"] == 3


@pytest.mark.asyncio
async def test_update_flow_merges_http_secrets_by_step_id_after_reorder(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_FakeEncryptionService(),
    )

    flow_id = uuid4()
    first_step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": _http_authored_config("enc:first-secret"),
        },
        deep=True,
    )
    second_step = _step(step_order=2).model_copy(
        update={
            "input_source": "http_get",
            "input_config": _http_authored_config("enc:second-secret"),
        },
        deep=True,
    )
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[first_step, second_step],
    )
    flow_repo.get.return_value = existing
    flow_repo.update.side_effect = lambda flow, tenant_id, expected_revision=None: flow

    first_incoming = first_step.model_copy(
        update={
            "step_order": 2,
            "input_source": "http_get",
            "input_config": _http_authored_config(SECRET_SENTINEL),
        },
        deep=True,
    )
    second_incoming = second_step.model_copy(
        update={
            "step_order": 1,
            "input_source": "http_get",
            "input_config": _http_authored_config(SECRET_SENTINEL),
        },
        deep=True,
    )

    await service.update_flow(
        flow_id=flow_id,
        steps=[second_incoming, first_incoming],
    )

    persisted = flow_repo.update.await_args.kwargs["flow"]
    persisted_by_id = {step.id: step for step in persisted.steps}
    assert (
        persisted_by_id[first_step.id].input_config["custom_headers"][0]["value"]
        == "enc:first-secret"
    )
    assert (
        persisted_by_id[second_step.id].input_config["custom_headers"][0]["value"]
        == "enc:second-secret"
    )


@pytest.mark.asyncio
async def test_update_flow_rejects_unknown_step_id(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = existing
    incoming = _step(step_order=1).model_copy(update={"id": uuid4()}, deep=True)

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow(flow_id=flow_id, steps=[incoming])

    assert exc_info.value.code == "unknown_step_id"


@pytest.mark.asyncio
async def test_update_flow_rejects_idless_step_secret_sentinel(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = existing
    new_step = _step(step_order=2).model_copy(
        update={
            "id": None,
            "input_source": "http_get",
            "input_config": _http_authored_config(SECRET_SENTINEL),
        },
        deep=True,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow(flow_id=flow_id, steps=[existing.steps[0], new_step])

    assert exc_info.value.code == "sentinel_secret_requires_step_id"


@pytest.mark.asyncio
async def test_update_flow_rejects_duplicate_step_id(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    first_step = _step(step_order=1)
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[first_step],
    )
    flow_repo.get.return_value = existing
    duplicate = first_step.model_copy(
        update={"step_order": 2, "input_source": "previous_step"}, deep=True
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow(flow_id=flow_id, steps=[first_step, duplicate])

    assert exc_info.value.code == "duplicate_step_id"


@pytest.mark.asyncio
async def test_update_flow_rejects_duplicate_step_order(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    first_step = _step(step_order=1)
    second_step = _step(step_order=2)
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[first_step, second_step],
    )
    flow_repo.get.return_value = existing

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow(
            flow_id=flow_id,
            steps=[
                first_step,
                second_step.model_copy(update={"step_order": 1}, deep=True),
            ],
        )

    assert exc_info.value.code == "duplicate_step_order"


@pytest.mark.asyncio
async def test_get_flow_assistant_snapshots_batches_and_deduplicates_assistant_ids(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    assistant_id = uuid4()
    other_assistant_id = uuid4()
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Snapshot flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1).model_copy(update={"assistant_id": assistant_id}),
            _step(step_order=2).model_copy(update={"assistant_id": assistant_id}),
            _step(step_order=3).model_copy(update={"assistant_id": other_assistant_id}),
        ],
    )
    expected = {
        assistant_id: {"instructions": "A", "model_ref": None, "knowledge_refs": []},
        other_assistant_id: {
            "instructions": "B",
            "model_ref": None,
            "knowledge_refs": [],
        },
    }
    flow_repo.get_assistant_snapshots.return_value = expected

    result = await service.get_flow_assistant_snapshots(flow)

    assert result == expected
    flow_repo.get_assistant_snapshots.assert_awaited_once_with(
        assistant_ids=[assistant_id, other_assistant_id],
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_publish_flow_pins_template_metadata_for_template_fill(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    template_asset_id = uuid4()
    template_file_id = uuid4()
    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Template flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json={"form_schema": {"fields": [{"name": "title", "type": "text"}]}},
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1).model_copy(
                update={
                    "output_mode": "template_fill",
                    "output_type": "docx",
                    "output_config": {
                        "template_asset_id": str(template_asset_id),
                        "bindings": {"section": "{{flow_input.title}}"},
                    },
                }
            )
        ],
    )
    flow_repo.get.return_value = source_flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = source_flow.model_copy(
        update={"published_version": 1}
    )
    asset = _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
        asset_id=template_asset_id,
    )

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    output_config = definition["steps"][0]["output_config"]
    assert output_config["template_asset_id"] == str(asset.id)
    assert "template_file_id" not in output_config
    assert output_config["template_checksum"] == "abc123"
    assert output_config["template_name"] == "rapport.docx"
    assert output_config["placeholders"] == ["section"]


@pytest.mark.asyncio
async def test_publish_flow_preserves_template_placeholder_order(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    template_asset_id = uuid4()
    template_file_id = uuid4()
    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Ordered template flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1),
            _step(step_order=1).model_copy(
                update={
                    "step_order": 2,
                    "user_description": "Sammanställ dokument",
                    "input_source": "previous_step",
                    "output_mode": "template_fill",
                    "output_type": "docx",
                    "output_config": {
                        "template_asset_id": str(template_asset_id),
                        "bindings": {
                            "bakgrund": "{{step_1.output.text}}",
                            "analys": "{{step_1.output.text}}",
                            "slutsats": "{{step_1.output.text}}",
                        },
                    },
                }
            ),
        ],
    )
    flow_repo.get.return_value = source_flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = source_flow.model_copy(
        update={"published_version": 1}
    )
    _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
        asset_id=template_asset_id,
        placeholder_names=("bakgrund", "analys", "slutsats"),
    )

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    output_config = definition["steps"][1]["output_config"]
    assert output_config["placeholders"] == ["bakgrund", "analys", "slutsats"]


@pytest.mark.asyncio
async def test_update_flow_allows_incomplete_template_fill_during_draft_editing(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    existing = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    draft_steps = [
        existing.steps[0].model_copy(
            update={
                "output_mode": "template_fill",
                "output_type": "docx",
                "output_config": {"bindings": {}},
            }
        )
    ]
    flow_repo.get.return_value = existing
    flow_repo.update.return_value = existing.model_copy(update={"steps": draft_steps})

    updated = await service.update_flow(flow_id=flow_id, steps=draft_steps)

    assert updated.steps[0].output_mode == "template_fill"
    assert updated.steps[0].output_config == {"bindings": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("asset_error", "expected_code"),
    [
        (None, None),
        (NotFoundException("Missing asset"), FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE),
        (
            BadRequestException(
                "Missing content", code=FlowApiErrorCode.TEMPLATE_MISSING_CONTENT.value
            ),
            FlowApiErrorCode.TEMPLATE_MISSING_CONTENT,
        ),
    ],
    ids=["missing_bindings", "inaccessible_asset", "missing_content"],
)
async def test_publish_flow_rejects_invalid_template_before_version_write(
    user,
    asset_error: NotFoundException | BadRequestException | None,
    expected_code: FlowApiErrorCode | None,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    template_asset_id = uuid4()
    template_file_id = uuid4()
    flow_repo.get.return_value = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Template flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1).model_copy(
                update={
                    "output_mode": "template_fill",
                    "output_type": "docx",
                    "output_config": {
                        "template_asset_id": str(template_asset_id),
                        "bindings": {},
                    },
                }
            )
        ],
    )

    _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
        asset_id=template_asset_id,
    )

    service.template_asset_service.get_asset_for_publication.side_effect = asset_error
    with pytest.raises(BadRequestException) as exc_info:
        await service.publish_flow(flow_id=flow_id)
    if asset_error is None:
        assert "missing bindings" in str(exc_info.value)
    else:
        assert exc_info.value.code == expected_code.value
        if isinstance(asset_error, BadRequestException):
            assert exc_info.value is asset_error
    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_flow_allows_explicit_empty_template_binding(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    template_asset_id = uuid4()
    template_file_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Template flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1).model_copy(
                update={
                    "output_mode": "template_fill",
                    "output_type": "docx",
                    "output_config": {
                        "template_asset_id": str(template_asset_id),
                        "bindings": {"optional_section": ""},
                    },
                }
            )
        ],
    )
    flow_repo.get.return_value = source_flow
    flow_repo.allocate_next_version.return_value = 1
    flow_repo.update.return_value = source_flow.model_copy(
        update={"published_version": 1}
    )
    _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
        asset_id=template_asset_id,
        placeholder_names=("optional_section",),
    )

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["steps"][0]["output_config"]["bindings"]["optional_section"] == ""


@pytest.mark.asyncio
async def test_create_flow_rejects_forward_step_reference(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={"input_bindings": {"question": "{{step_1.output.summary}}"}}
    )

    with pytest.raises(BadRequestException):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_update_flow_allows_explicit_description_clear(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Update Flow",
        description="to be cleared",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    expected = source_flow.model_copy(update={"description": None})
    flow_repo.get.return_value = source_flow
    flow_repo.update.return_value = expected

    result = await service.update_flow(
        flow_id=flow_id,
        description=None,
        name=NOT_PROVIDED,
    )

    assert result.description is None
    flow_repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_encrypts_authored_http_secret_values(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_FakeEncryptionService(),
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/input",
                "auth": {
                    "mode": "bearer_token",
                    "token": "Bearer topsecret",
                },
                "custom_headers": [
                    {"name": "X-Trace", "value": "visible", "secret": False}
                ],
            },
            "output_mode": "http_post",
            "output_config": {
                "url": "https://example.org/output",
                "auth": {
                    "mode": "api_key",
                    "header_name": "X-Api-Key",
                    "key": "abc123",
                },
            },
        }
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    input_config = created.steps[0].input_config
    output_config = created.steps[0].output_config
    assert input_config["auth"]["token"] == "enc:Bearer topsecret"
    assert input_config["custom_headers"][0]["value"] == "visible"
    assert output_config["auth"]["key"] == "enc:abc123"


@pytest.mark.asyncio
async def test_create_flow_rejects_http_secret_when_encryption_inactive(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_InactiveEncryptionService(),
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/input",
                "auth": {"mode": "bearer_token", "token": "Bearer topsecret"},
            },
        }
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )

    assert "ENCRYPTION_KEY" in str(excinfo.value)
    assert "topsecret" not in str(excinfo.value)
    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_secret_disguised_with_encryption_prefix(user):
    """The prefix is authored syntax, not proof that a value is ciphertext."""
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_InactiveEncryptionService(),
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/input",
                "auth": {
                    "mode": "bearer_token",
                    "token": "enc:fernet:v1:not-really-encrypted",
                },
            },
        }
    )

    with pytest.raises(BadRequestException):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )

    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_url_userinfo_behind_a_templated_host(user):
    """Userinfo is authored literally, so a template must not defer it past save."""
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_FakeEncryptionService(),
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://alice:secret@{{host}}/input",
                "auth": {"mode": "none"},
            },
        }
    )

    with pytest.raises(BadRequestException):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )

    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_persists_secret_free_http_config_when_encryption_inactive(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_InactiveEncryptionService(),
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/input",
                "auth": {"mode": "none"},
                "custom_headers": [
                    {"name": "X-Trace", "value": "visible", "secret": False}
                ],
            },
        }
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    assert created.steps[0].input_config["custom_headers"][0]["value"] == "visible"


def _http_step_with_token(token, *, step_id=None, step_order: int = 1):
    step = _step(step_order=step_order).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/input",
                "auth": {"mode": "bearer_token", "token": token},
            },
        }
    )
    return step if step_id is None else step.model_copy(update={"id": step_id})


def _published_flow_for_update(user, steps):
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        steps=steps,
        published_version=None,
    )


@pytest.mark.asyncio
async def test_update_flow_rejects_new_http_secret_when_encryption_inactive(user):
    step_id = uuid4()
    stored = _published_flow_for_update(
        user, [_http_step_with_token("enc:stored-secret", step_id=step_id)]
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_InactiveEncryptionService(),
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.update_flow(
            flow_id=stored.id,
            steps=[_http_step_with_token("brand-new-secret", step_id=step_id)],
        )

    assert "ENCRYPTION_KEY" in str(excinfo.value)
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_keeps_stored_secret_behind_sentinel_when_inactive(user):
    """A sentinel is a reference to the stored row, so the edit stays possible."""
    step_id = uuid4()
    stored = _published_flow_for_update(
        user, [_http_step_with_token("enc:stored-secret", step_id=step_id)]
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_InactiveEncryptionService(),
    )

    updated = await service.update_flow(
        flow_id=stored.id,
        steps=[_http_step_with_token(SECRET_SENTINEL, step_id=step_id)],
    )

    assert updated.steps[0].input_config["auth"]["token"] == "enc:stored-secret"


@pytest.mark.asyncio
async def test_origin_change_refuses_save_without_claiming_the_credential_was_deleted(
    user,
):
    # Mutant: restore across origins or describe a destination refusal as a deleted credential.
    step_id = uuid4()
    stored = _published_flow_for_update(
        user, [_http_step_with_token("enc:stored-secret", step_id=step_id)]
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_FakeEncryptionService(),
    )
    incoming = _http_step_with_token(SECRET_SENTINEL, step_id=step_id)
    incoming.input_config["url"] = "https://other.example.org/input"

    with pytest.raises(BadRequestException) as excinfo:
        await service.update_flow(flow_id=stored.id, steps=[incoming])

    assert "unavailable for this destination" in str(excinfo.value)
    assert "stored-secret" not in str(excinfo.value)
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_sentinel_that_can_resolve_to_nothing(user):
    flow_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_FakeEncryptionService(),
    )

    with pytest.raises(BadRequestException):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_http_step_with_token(SECRET_SENTINEL)],
            metadata_json=None,
        )

    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_encrypts_authored_value_wearing_encryption_prefix(user):
    """An author-typed prefix must not suppress encryption on the active path."""
    flow_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_FakeEncryptionService(),
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[_http_step_with_token("enc:not-really-encrypted")],
        metadata_json=None,
    )

    assert (
        created.steps[0].input_config["auth"]["token"] == "enc:enc:not-really-encrypted"
    )


def _credential_config(field: str, value: object) -> dict[str, Any]:
    """An authored HTTP config whose one credential field holds `value`."""
    base: dict[str, Any] = {"url": "https://example.org/hook", "auth": {"mode": "none"}}
    if field == "auth.token":
        base["auth"] = {"mode": "bearer_token", "token": value}
    elif field == "auth.key":
        base["auth"] = {"mode": "api_key", "header_name": "X-Key", "key": value}
    elif field == "auth.password":
        base["auth"] = {"mode": "basic_auth", "username": "u", "password": value}
    else:
        base["custom_headers"] = [
            {"name": "X-Open", "value": "plain"},
            {"name": "X-Secret", "value": value, "secret": True},
        ]
    return base


_CREDENTIAL_CASES = [
    pytest.param(side, field, id=f"{side}-{field}")
    for side in ("input_config", "output_config")
    for field in (
        "auth.token",
        "auth.key",
        "auth.password",
        "custom_headers[1].value",
    )
]
_TEMPLATED_CREDENTIAL = "{{ step_1.output.text }}"


def _http_step_with_credential(side: str, config: dict[str, Any], **update: Any):
    fields: dict[str, Any] = (
        {"input_source": "http_get", "input_type": "text", side: config}
        if side == "input_config"
        else {"output_mode": "http_post", "output_type": "text", side: config}
    )
    return _step(step_order=1).model_copy(update={**fields, **update})


def _assert_credential_refusal(exc: BaseException, *, side: str, field: str) -> None:
    assert isinstance(exc, BadRequestException)
    assert f"{side}.{field}" in str(exc)
    assert _TEMPLATED_CREDENTIAL not in str(exc)
    assert exc.context["field"] == f"{side}.{field}"
    assert exc.context["issue_code"] == "flow_step_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "field"), _CREDENTIAL_CASES)
async def test_create_flow_refuses_a_template_in_a_credential(user, side, field):
    flow_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_FakeEncryptionService(),
    )
    step = _http_step_with_credential(
        side, _credential_config(field, _TEMPLATED_CREDENTIAL)
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.create_flow(space_id=uuid4(), name="Flow", steps=[step])

    _assert_credential_refusal(excinfo.value, side=side, field=field)
    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "field"), _CREDENTIAL_CASES)
async def test_create_flow_keeps_a_literal_credential_and_a_templated_open_field(
    user, side, field
):
    flow_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_FakeEncryptionService(),
    )
    config = _credential_config(field, "literal-{single}-credential")
    config["url"] = "https://example.org/{{ flow_input.case }}"
    step = _http_step_with_credential(side, config)

    created = await service.create_flow(space_id=uuid4(), name="Flow", steps=[step])

    assert getattr(created.steps[0], side)["url"].endswith("{{ flow_input.case }}")
    flow_repo.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "field"), _CREDENTIAL_CASES)
async def test_update_flow_refuses_a_new_template_in_a_credential(user, side, field):
    step_id = uuid4()
    stored = _published_flow_for_update(
        user,
        [
            _http_step_with_credential(
                side, _credential_config(field, "enc:stored-secret"), id=step_id
            )
        ],
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_FakeEncryptionService(),
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.update_flow(
            flow_id=stored.id,
            steps=[
                _http_step_with_credential(
                    side,
                    _credential_config(field, _TEMPLATED_CREDENTIAL),
                    id=step_id,
                )
            ],
        )

    _assert_credential_refusal(excinfo.value, side=side, field=field)
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "field"), _CREDENTIAL_CASES)
async def test_update_flow_refuses_a_retained_credential_that_holds_a_template(
    user, side, field
):
    # The incoming step keeps the stored credential behind a sentinel, so the
    # step validation never sees it: it is read once the stored value is merged.
    encryption = _OpaqueEncryptionService()
    step_id = uuid4()
    stored = _published_flow_for_update(
        user,
        [
            _http_step_with_credential(
                side,
                _credential_config(field, encryption.encrypt(_TEMPLATED_CREDENTIAL)),
                id=step_id,
            )
        ],
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=encryption,
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.update_flow(
            flow_id=stored.id,
            steps=[
                _http_step_with_credential(
                    side, _credential_config(field, SECRET_SENTINEL), id=step_id
                )
            ],
        )

    _assert_credential_refusal(excinfo.value, side=side, field=field)
    flow_repo.update.assert_not_awaited()


_BOGUS_HTTP_CONFIG = {"url": "https://example.org/hook", "auth": {"mode": "bogus"}}
_UNACCEPTED_HTTP_CONFIGS = [
    pytest.param(_BOGUS_HTTP_CONFIG, id="bogus-auth-mode"),
    pytest.param({"url": "https://example.org/hook"}, id="missing-auth"),
    pytest.param({"url": "not a url", "auth": {"mode": "none"}}, id="malformed-url"),
    pytest.param(
        {
            "url": "https://alice:secret@{{ flow_input.host }}/hook",
            "auth": {"mode": "none"},
        },
        id="templated-userinfo",
    ),
    pytest.param(
        {
            "url": "ftp://example.org/{{ flow_input.id }}",
            "auth": {"mode": "none"},
        },
        id="fixed-non-http-scheme-before-a-template",
    ),
    pytest.param(
        {
            "url": "https://example.org/hook",
            "auth": {"mode": "none"},
            "timeout_seconds": 100000,
        },
        id="timeout-over-the-cap",
    ),
]

_UNSAFE_CREDENTIAL_DESTINATIONS = [
    # Mutant: save/publish credentials whose origin is plaintext or run-selected.
    pytest.param(
        {
            "url": "http://example.org/hook",
            "auth": {
                "mode": "bearer_token",
                "token": _OpaqueEncryptionService().encrypt("synthetic-credential"),
            },
        },
        id="credential-origin-bearer-http",
    ),
    pytest.param(
        {
            "url": "https://{{ datum }}.example.org/hook",
            "auth": {
                "mode": "api_key",
                "key": _OpaqueEncryptionService().encrypt("synthetic-credential"),
            },
        },
        id="credential-origin-api-key-dynamic-host",
    ),
    pytest.param(
        {
            "url": "https://example.org:{{ datum }}/hook",
            "auth": {
                "mode": "basic_auth",
                "username": "synthetic-user",
                "password": _OpaqueEncryptionService().encrypt("synthetic-credential"),
            },
        },
        id="credential-origin-basic-dynamic-port",
    ),
    pytest.param(
        {
            "url": "{{ datum }}://example.org/hook",
            "auth": {"mode": "none"},
            "custom_headers": [
                {
                    "name": "X-Integration-Credential",
                    "value": _OpaqueEncryptionService().encrypt("synthetic-credential"),
                    "secret": True,
                }
            ],
        },
        id="credential-origin-secret-header-dynamic-scheme",
    ),
]


def _flow_with_bogus_http_config(user, side, config):
    return _published_flow_for_update(
        user, [_http_step_with_credential(side, dict(config))]
    )


def _assert_typed_http_config_refusal(error: BaseException, *, side: str) -> None:
    assert isinstance(error, BadRequestException)
    assert error.code == "typed_io_http_invalid_config"
    assert error.context["step_order"] == 1
    assert error.context["issue_code"] == "flow_step_invalid"
    assert error.context["field"].startswith(side)
    assert "alice:secret" not in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config", _UNACCEPTED_HTTP_CONFIGS + _UNSAFE_CREDENTIAL_DESTINATIONS
)
@pytest.mark.parametrize("side", ["input_config", "output_config"])
async def test_create_flow_reports_the_typed_code_of_a_config_the_runtime_rejects(
    user, side, config
):
    flow_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_OpaqueEncryptionService(),
    )
    step = _http_step_with_credential(side, dict(config))

    with pytest.raises(BadRequestException) as excinfo:
        await service.create_flow(space_id=uuid4(), name="Flow", steps=[step])

    _assert_typed_http_config_refusal(excinfo.value, side=side)
    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config", _UNACCEPTED_HTTP_CONFIGS + _UNSAFE_CREDENTIAL_DESTINATIONS
)
@pytest.mark.parametrize("side", ["input_config", "output_config"])
async def test_publish_flow_refuses_a_stored_http_config_that_authoring_rejects(
    user, side, config
):
    stored = _flow_with_bogus_http_config(user, side, config)
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.allocate_next_version.return_value = 1
    version_repo = AsyncMock()
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_OpaqueEncryptionService(),
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.publish_flow(flow_id=stored.id)

    _assert_typed_http_config_refusal(excinfo.value, side=side)
    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config", _UNACCEPTED_HTTP_CONFIGS + _UNSAFE_CREDENTIAL_DESTINATIONS
)
@pytest.mark.parametrize("side", ["input_config", "output_config"])
async def test_update_flow_refuses_a_stored_http_config_that_authoring_rejects(
    user, side, config
):
    stored = _flow_with_bogus_http_config(user, side, config)
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=_OpaqueEncryptionService(),
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.update_flow(flow_id=stored.id, name="Renamed")

    _assert_typed_http_config_refusal(excinfo.value, side=side)
    flow_repo.update.assert_not_awaited()


@pytest.mark.parametrize(
    "config",
    [param for param in _UNACCEPTED_HTTP_CONFIGS if param.id != "timeout-over-the-cap"],
)
@pytest.mark.parametrize("side", ["input_config", "output_config"])
def test_the_stored_credential_scan_names_the_step_of_a_config_that_does_not_parse(
    user, side, config
):
    # The step validation reads the config first, so this is the scan's own
    # answer for a stored config that reaches it: a step-scoped error, never a
    # bare pydantic one. (The timeout cap is the runtime's and is held at the
    # run preflight.)
    service = _service(
        user=user,
        flow_repo=AsyncMock(),
        version_repo=AsyncMock(),
        encryption_service=_OpaqueEncryptionService(),
    )
    step = _http_step_with_credential(side, dict(config))

    with pytest.raises(BadRequestException) as excinfo:
        service._reject_templated_stored_secrets([step])

    _assert_typed_http_config_refusal(excinfo.value, side=side)
    assert "bogus" not in str(excinfo.value)
    assert "not a url" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_update_flow_keeps_a_retained_literal_credential(user):
    encryption = _OpaqueEncryptionService()
    step_id = uuid4()
    stored = _published_flow_for_update(
        user,
        [
            _http_step_with_credential(
                "output_config",
                _credential_config("auth.token", encryption.encrypt("literal-token")),
                id=step_id,
            )
        ],
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        encryption_service=encryption,
    )

    await service.update_flow(
        flow_id=stored.id,
        steps=[
            _http_step_with_credential(
                "output_config",
                _credential_config("auth.token", SECRET_SENTINEL),
                id=step_id,
            )
        ],
    )

    flow_repo.update.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "field"), _CREDENTIAL_CASES)
async def test_publish_flow_refuses_a_stored_credential_that_holds_a_template(
    user, side, field
):
    # Stored credentials are ciphertext that shows nothing of what it holds:
    # the check reads them as the runtime does, decrypted.
    encryption = _OpaqueEncryptionService()
    stored_value = encryption.encrypt(_TEMPLATED_CREDENTIAL)
    assert not iter_template_expressions(stored_value)
    stored = _published_flow_for_update(
        user,
        [_http_step_with_credential(side, _credential_config(field, stored_value))],
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.allocate_next_version.return_value = 1
    version_repo = AsyncMock()
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=encryption,
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.publish_flow(flow_id=stored.id)

    _assert_credential_refusal(excinfo.value, side=side, field=field)
    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "field"), _CREDENTIAL_CASES)
async def test_publish_flow_allows_a_stored_literal_credential(user, side, field):
    stored = _published_flow_for_update(
        user,
        [
            _http_step_with_credential(
                side,
                _credential_config(
                    field, _OpaqueEncryptionService().encrypt("literal-{single}")
                ),
            )
        ],
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    flow_repo.allocate_next_version.return_value = 1
    version_repo = AsyncMock()
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_OpaqueEncryptionService(),
    )

    await service.publish_flow(flow_id=stored.id)

    version_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_rejects_previous_step_input_for_first_step(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(update={"input_source": "previous_step"})

    with pytest.raises(BadRequestException):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_create_flow_allows_http_get_input_source_with_valid_config(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create = AsyncMock(side_effect=lambda **kwargs: kwargs["flow"])
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/source",
                "auth": {"mode": "none"},
                "timeout_seconds": 12,
            },
            "input_type": "text",
        }
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    assert created.steps[0].input_source == "http_get"
    assert created.steps[0].input_config["url"] == "https://example.org/source"


@pytest.mark.asyncio
async def test_create_flow_rejects_http_get_input_without_url(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_get",
            "input_config": {"auth": {"mode": "none"}, "timeout_seconds": 5},
        }
    )

    with pytest.raises(BadRequestException, match="HTTP_MISSING_URL"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_legacy_http_post_input_before_persistence(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_post",
            "input_config": {
                "url": "https://example.org/source",
                "auth": {"mode": "none"},
            },
        }
    )

    with pytest.raises(
        BadRequestException, match="unsupported input_source 'http_post'"
    ):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )

    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_http_post_output_without_url(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={
            "output_mode": "http_post",
            "output_config": {"auth": {"mode": "none"}},
        }
    )

    with pytest.raises(BadRequestException, match="HTTP_MISSING_URL"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_create_flow_allows_http_post_output_with_valid_config(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create = AsyncMock(side_effect=lambda **kwargs: kwargs["flow"])
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={
            "output_mode": "http_post",
            "output_config": {
                "url": "https://example.org/hook",
                "auth": {"mode": "none"},
                "timeout_seconds": 25,
                "body": {
                    "mode": "text_template",
                    "template": '{"message":"{{flow_input.text}}"}',
                },
            },
        }
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    assert created.steps[0].output_mode == "http_post"
    assert created.steps[0].output_config["url"] == "https://example.org/hook"


@pytest.mark.asyncio
async def test_create_flow_rejects_assistants_outside_space_or_tenant(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.return_value = AsyncMock()
    flow_repo.get_assistant_scope_rows.return_value = []

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException, match="outside the selected space or tenant"
    ):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step(step_order=1)],
            metadata_json=None,
        )

    flow_repo.get_assistant_scope_rows.assert_awaited_once()
    kwargs = flow_repo.get_assistant_scope_rows.await_args.kwargs
    assert kwargs["space_id"]
    assert kwargs["tenant_id"] == user.tenant_id
    assert len(kwargs["assistant_ids"]) == 1


@pytest.mark.asyncio
async def test_create_flow_allows_scoped_assistant_references_before_flow_exists(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_id = uuid4()
    flow_repo.create.side_effect = lambda **kwargs: kwargs["flow"]
    flow_repo.get_assistant_scope_rows.return_value = [
        SimpleNamespace(
            id=assistant_id,
            origin=AssistantOrigin.USER.value,
            managing_flow_id=None,
        )
    ]

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
    )
    step = _step(step_order=1).model_copy(update={"assistant_id": assistant_id})

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    assert created.steps[0].assistant_id == assistant_id
    flow_repo.get_assistant_scope_rows.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_allows_empty_steps_with_strict_flow_managed_enforcement(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda **kwargs: kwargs["flow"]

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[],
        metadata_json=None,
    )

    assert created.steps == []
    flow_repo.get_assistant_scope_rows.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_rejects_flow_managed_assistants_not_owned_by_flow(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_id = uuid4()
    assistant_id = uuid4()
    flow_repo.get_assistant_scope_rows.return_value = [
        SimpleNamespace(
            id=assistant_id,
            origin=AssistantOrigin.FLOW_MANAGED.value,
            managing_flow_id=uuid4(),
        )
    ]

    existing_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1).model_copy(update={"assistant_id": assistant_id})],
    )
    flow_repo.get.return_value = existing_flow

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException,
        match="Flow steps must reference flow-managed assistants owned by the flow",
    ):
        await service.update_flow(flow_id=flow_id, steps=[existing_flow.steps[0]])


@pytest.mark.asyncio
async def test_publish_flow_rejects_flow_managed_assistants_not_owned_by_flow(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_id = uuid4()
    assistant_id = uuid4()
    flow_repo.get_assistant_scope_rows.return_value = [
        SimpleNamespace(
            id=assistant_id,
            origin=AssistantOrigin.FLOW_MANAGED.value,
            managing_flow_id=uuid4(),
        )
    ]

    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1).model_copy(update={"assistant_id": assistant_id})],
    )
    flow_repo.get.return_value = source_flow

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException,
        match="Flow steps must reference flow-managed assistants owned by the flow",
    ):
        await service.publish_flow(flow_id=flow_id)


@pytest.mark.asyncio
async def test_publish_flow_rejects_assistant_model_below_required_security_level(user):
    user.tenant.security_enabled = True
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_id = uuid4()
    assistant_id = uuid4()
    flow_repo.get_assistant_scope_rows.return_value = [
        SimpleNamespace(
            id=assistant_id,
            origin=AssistantOrigin.FLOW_MANAGED.value,
            managing_flow_id=flow_id,
        )
    ]

    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1).model_copy(update={"assistant_id": assistant_id})],
    )
    flow_repo.get.return_value = source_flow

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
        space_service=AsyncMock(),
    )
    service.space_service.get_space.return_value = SimpleNamespace(
        security_classification=SimpleNamespace(security_level=3)
    )
    service.assistant_service.get_assistant.return_value = (
        SimpleNamespace(
            get_prompt_text=lambda: "",
            completion_model=SimpleNamespace(
                security_classification=SimpleNamespace(security_level=2)
            ),
            collections=[],
            websites=[],
            integration_knowledge_list=[],
            mcp_servers=[],
        ),
        [],
    )

    with pytest.raises(BadRequestException, match="security classification"):
        await service.publish_flow(flow_id=flow_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        pytest.param("{{ step_1.output }}", id="direct"),
        pytest.param("{{ föregående_steg }}", id="previous-step-shorthand"),
    ],
)
async def test_publish_flow_rejects_write_down_of_a_read_previous_step(user, question):
    user.tenant.security_enabled = True
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_id = uuid4()
    assistant_a = uuid4()
    assistant_b = uuid4()
    flow_repo.get_assistant_scope_rows.return_value = [
        SimpleNamespace(
            id=assistant_id,
            origin=AssistantOrigin.FLOW_MANAGED.value,
            managing_flow_id=flow_id,
        )
        for assistant_id in (assistant_a, assistant_b)
    ]
    flow_repo.get.return_value = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1).model_copy(
                update={
                    "assistant_id": assistant_a,
                    "output_classification_override": 3,
                }
            ),
            _step(step_order=2).model_copy(
                update={
                    "assistant_id": assistant_b,
                    # The question is the whole input; input_source is unused.
                    "input_bindings": {"question": question},
                    "output_classification_override": 1,
                }
            ),
        ],
    )
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
        space_service=AsyncMock(),
    )
    service.space_service.get_space.return_value = SimpleNamespace(
        security_classification=SimpleNamespace(security_level=1)
    )
    service.assistant_service.get_assistant.return_value = (
        SimpleNamespace(
            get_prompt_text=lambda: "",
            completion_model=SimpleNamespace(
                security_classification=SimpleNamespace(security_level=3)
            ),
            collections=[],
            websites=[],
            integration_knowledge_list=[],
            mcp_servers=[],
        ),
        [],
    )

    with pytest.raises(BadRequestException, match="output classification override"):
        await service.publish_flow(flow_id=flow_id)
    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_flow_rejects_output_override_write_down(user):
    user.tenant.security_enabled = True
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_id = uuid4()
    assistant_a = uuid4()
    assistant_b = uuid4()
    flow_repo.get_assistant_scope_rows.return_value = [
        SimpleNamespace(
            id=assistant_a,
            origin=AssistantOrigin.FLOW_MANAGED.value,
            managing_flow_id=flow_id,
        ),
        SimpleNamespace(
            id=assistant_b,
            origin=AssistantOrigin.FLOW_MANAGED.value,
            managing_flow_id=flow_id,
        ),
    ]

    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[
            _step(step_order=1).model_copy(
                update={
                    "assistant_id": assistant_a,
                    "output_classification_override": 3,
                }
            ),
            _step(step_order=2).model_copy(
                update={
                    "assistant_id": assistant_b,
                    "output_classification_override": 1,
                }
            ),
        ],
    )
    flow_repo.get.return_value = source_flow

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
        space_service=AsyncMock(),
    )
    service.space_service.get_space.return_value = SimpleNamespace(
        security_classification=SimpleNamespace(security_level=1)
    )
    service.assistant_service.get_assistant.side_effect = [
        (
            SimpleNamespace(
                get_prompt_text=lambda: "",
                completion_model=SimpleNamespace(
                    security_classification=SimpleNamespace(security_level=3)
                ),
                collections=[],
                websites=[],
                integration_knowledge_list=[],
                mcp_servers=[],
            ),
            [],
        ),
        (
            SimpleNamespace(
                get_prompt_text=lambda: "",
                completion_model=SimpleNamespace(
                    security_classification=SimpleNamespace(security_level=3)
                ),
                collections=[],
                websites=[],
                integration_knowledge_list=[],
                mcp_servers=[],
            ),
            [],
        ),
    ]

    with pytest.raises(BadRequestException, match="output classification override"):
        await service.publish_flow(flow_id=flow_id)


@dataclass(frozen=True)
class _ClassifiedStep:
    """One step of a classified chain, as the API hands it to the service."""

    model_level: int
    input_source: str = "previous_step"
    override: int | None = None
    question: str | None = None
    http: bool = False
    output_mode: str = "pass_through"
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None


_MISMATCH = "flow_step_security_classification_mismatch"
_WRITE_DOWN = "flow_step_output_classification_write_down"
_HIGH_FIRST_STEP = _ClassifiedStep(model_level=3, input_source="flow_input", override=3)
_LITERAL_SECOND_STEP = _ClassifiedStep(model_level=1, question="Fast text.")


def _classified_chain(user, steps: list[_ClassifiedStep], *, space_level: int = 1):
    """A saved draft whose steps carry the given classifications.

    Steps are built through ``FlowStep`` validation, so ``input_source`` is the
    ``FlowInputSource`` member every persisted or API-supplied step carries (a
    ``model_copy(update=...)`` would leave a bare string and hide how the
    service reads the field).
    """
    user.tenant.security_enabled = True
    flow_id = uuid4()
    space_id = uuid4()
    assistants = []
    flow_steps = []
    for order, spec in enumerate(steps, start=1):
        assistant = _build_assistant(flow_id=flow_id, space_id=space_id, user=user)
        assistant.completion_model = SimpleNamespace(
            security_classification=_classification(spec.model_level),
            can_access=True,
        )
        assistants.append(assistant)
        step = FlowStep(
            id=uuid4(),
            assistant_id=assistant.id,
            step_order=order,
            user_description=f"Step {order}",
            input_source=spec.input_source,
            input_type="text",
            output_mode=spec.output_mode,
            output_type="docx" if spec.output_mode == "template_fill" else "text",
            input_bindings=(
                {"question": spec.question} if spec.question is not None else None
            ),
            input_config=(
                {"url": "https://example.org/input", "auth": {"mode": "none"}}
                if spec.http
                else spec.input_config
            ),
            output_config=spec.output_config,
            output_classification_override=spec.override,
        )
        assert isinstance(step.input_source, FlowInputSource)
        flow_steps.append(step)

    flow_repo = AsyncMock()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=space_id,
        name="Classified",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=flow_steps,
    )
    flow_repo.get.return_value = flow
    flow_repo.update.side_effect = lambda flow, tenant_id, expected_revision=None: flow
    space_service = AsyncMock()
    space_service.get_space.return_value = _FlowSecuritySpaceStub(level=space_level)
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        space_service=space_service,
    )
    by_id = {assistant.id: assistant for assistant in assistants}
    service.assistant_service.get_assistant.side_effect = lambda assistant_id: (
        by_id[assistant_id],
        [],
    )
    return service, flow_repo, flow


async def _save(service: FlowService, flow: Flow, operation: str) -> None:
    if operation == "create":
        await service.create_flow(
            space_id=flow.space_id, name=flow.name, steps=flow.steps
        )
    else:
        await service.update_flow(flow_id=flow.id, steps=flow.steps)


def _rows_written(flow_repo: AsyncMock, operation: str) -> bool:
    return (
        flow_repo.create if operation == "create" else flow_repo.update
    ).await_count > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("steps", "code"),
    [
        pytest.param(
            [_HIGH_FIRST_STEP, _ClassifiedStep(model_level=1)],
            _MISMATCH,
            id="previous_step-low-model",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _ClassifiedStep(model_level=3, override=1),
            ],
            _WRITE_DOWN,
            id="previous_step-low-override",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _LITERAL_SECOND_STEP,
                _ClassifiedStep(model_level=1, input_source="all_previous_steps"),
            ],
            _MISMATCH,
            id="all_previous_steps-low-model",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _LITERAL_SECOND_STEP,
                _ClassifiedStep(
                    model_level=3,
                    input_source="all_previous_steps",
                    override=1,
                ),
            ],
            _WRITE_DOWN,
            id="all_previous_steps-low-override",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _ClassifiedStep(model_level=1, question="{{ step_1.output }}"),
            ],
            _MISMATCH,
            id="explicit-binding-low-model",
        ),
    ],
)
async def test_save_refuses_a_step_that_reads_a_classified_step_it_is_not_cleared_for(
    user, steps, code, operation
):
    service, flow_repo, flow = _classified_chain(user, steps)

    with pytest.raises(BadRequestException) as exc_info:
        await _save(service, flow, operation)

    assert exc_info.value.code == code
    assert not _rows_written(flow_repo, operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [_HIGH_FIRST_STEP, _ClassifiedStep(model_level=3, override=3)],
            id="previous_step-equal-level",
        ),
        pytest.param(
            [_HIGH_FIRST_STEP, _ClassifiedStep(model_level=4, override=3)],
            id="previous_step-higher-level",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _ClassifiedStep(
                    model_level=1,
                    input_source="http_get",
                    http=True,
                ),
            ],
            id="http_get-reads-no-prior-step",
        ),
        pytest.param(
            [_HIGH_FIRST_STEP, _LITERAL_SECOND_STEP],
            id="own-input-decides-alone",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _LITERAL_SECOND_STEP,
                _ClassifiedStep(model_level=1),
            ],
            id="previous_step-reads-only-the-step-before",
        ),
        pytest.param(
            [
                _ClassifiedStep(model_level=1, input_source="flow_input"),
                _ClassifiedStep(model_level=1),
            ],
            id="unclassified-chain",
        ),
    ],
)
async def test_save_accepts_a_step_cleared_for_everything_it_reads(
    user, steps, operation
):
    service, flow_repo, flow = _classified_chain(user, steps)

    await _save(service, flow, operation)

    assert _rows_written(flow_repo, operation)


def _authored_http(**fields: Any) -> dict[str, Any]:
    return {"url": "https://example.org/hook", "auth": {"mode": "none"}, **fields}


_READ_STEP_1 = "{{ step_1.output.text }}"


def _template_fill(binding: str, **fields: Any) -> _ClassifiedStep:
    """A template fill step: deterministic, so it has no model to clear."""
    return _ClassifiedStep(
        model_level=1,
        question="Fast text.",
        output_mode="template_fill",
        output_config={"bindings": {"beslut": binding}},
        **fields,
    )


def _http_post(config: dict[str, Any], **fields: Any) -> _ClassifiedStep:
    return _ClassifiedStep(
        question="Fast text.",
        output_mode="http_post",
        output_config=config,
        **fields,
    )


def _http_get(config: dict[str, Any], **fields: Any) -> _ClassifiedStep:
    return _ClassifiedStep(input_source="http_get", input_config=config, **fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("steps", "code"),
    [
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _template_fill(_READ_STEP_1),
                _ClassifiedStep(model_level=1),
            ],
            _MISMATCH,
            id="template_fill-binding-lifts-what-a-later-low-model-reads",
        ),
        pytest.param(
            [_HIGH_FIRST_STEP, _template_fill(_READ_STEP_1, override=1)],
            _WRITE_DOWN,
            id="template_fill-binding-low-override",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_post(
                    _authored_http(
                        body={
                            "mode": "json_template",
                            "template": f'{{"t": "{_READ_STEP_1}"}}',
                        }
                    ),
                    model_level=1,
                ),
            ],
            _MISMATCH,
            id="http_post-body-template-low-model",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_post(
                    _authored_http(url=f"https://example.org/hook/{_READ_STEP_1}"),
                    model_level=1,
                ),
            ],
            _MISMATCH,
            id="http_post-url-template-low-model",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_post(
                    _authored_http(url=f"https://example.org/hook/{_READ_STEP_1}"),
                    model_level=3,
                    override=1,
                ),
            ],
            _WRITE_DOWN,
            id="http_post-url-template-low-override",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_get(
                    _authored_http(url=f"https://example.org/lookup?q={_READ_STEP_1}"),
                    model_level=1,
                ),
            ],
            _MISMATCH,
            id="http_get-url-template-low-model",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_get(
                    _authored_http(url=f"https://example.org/lookup?q={_READ_STEP_1}"),
                    model_level=3,
                    override=1,
                ),
            ],
            _WRITE_DOWN,
            id="http_get-url-template-low-override",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _LITERAL_SECOND_STEP,
                _http_post(
                    _authored_http(url=f"https://example.org/hook/{_READ_STEP_1}"),
                    model_level=1,
                ),
            ],
            _MISMATCH,
            id="http_post-reads-a-step-that-is-not-the-previous-one",
        ),
    ],
)
async def test_save_refuses_a_step_that_reads_a_classified_step_through_its_config(
    user, steps, code, operation
):
    service, flow_repo, flow = _classified_chain(user, steps)

    with pytest.raises(BadRequestException) as exc_info:
        await _save(service, flow, operation)

    assert exc_info.value.code == code
    assert not _rows_written(flow_repo, operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _template_fill(_READ_STEP_1, override=3),
                _ClassifiedStep(model_level=3),
            ],
            id="template_fill-binding-cleared-downstream",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_post(
                    _authored_http(url=f"https://example.org/hook/{_READ_STEP_1}"),
                    model_level=3,
                ),
            ],
            id="http_post-template-equal-level",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_post(
                    _authored_http(url=f"https://example.org/hook/{_READ_STEP_1}"),
                    model_level=4,
                ),
            ],
            id="http_post-template-higher-level",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_get(
                    _authored_http(url=f"https://example.org/lookup?q={_READ_STEP_1}"),
                    model_level=3,
                ),
            ],
            id="http_get-template-equal-level",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _template_fill("{{ indata_text }}"),
                _ClassifiedStep(model_level=1),
            ],
            id="template_fill-binding-of-the-flow-input-reads-no-step",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _LITERAL_SECOND_STEP,
                _http_post(
                    _authored_http(url="https://example.org/hook/{{ step_2.status }}"),
                    model_level=1,
                ),
            ],
            id="http_post-template-of-an-unclassified-step",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_post(_authored_http(), model_level=1),
            ],
            id="http_post-without-a-template",
        ),
        pytest.param(
            [
                _HIGH_FIRST_STEP,
                _http_get(
                    _authored_http(url="https://example.org/lookup"), model_level=1
                ),
            ],
            id="http_get-without-a-template",
        ),
    ],
)
async def test_save_accepts_a_config_that_reads_only_what_the_step_is_cleared_for(
    user, steps, operation
):
    service, flow_repo, flow = _classified_chain(user, steps)

    await _save(service, flow, operation)

    assert _rows_written(flow_repo, operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("config", "reported"),
    [
        pytest.param(
            _authored_http(
                url=f"https://example.org/{_READ_STEP_1}",
                auth={"mode": "bearer_token", "token": ""},
            ),
            "HTTP_MISSING_AUTH",
            id="missing-credentials",
        ),
        pytest.param(
            {"url": f"https://example.org/{_READ_STEP_1}"},
            "authored HTTP config",
            id="flat-legacy-config",
        ),
    ],
)
async def test_save_reports_a_malformed_http_config_before_the_classification(
    user, config, reported, operation
):
    # The config also reads a classified step through its url, so the
    # classification check would refuse the save first if it ran first.
    service, flow_repo, flow = _classified_chain(
        user, [_HIGH_FIRST_STEP, _http_get(config, model_level=1)]
    )

    with pytest.raises(BadRequestException) as exc_info:
        await _save(service, flow, operation)

    assert exc_info.value.code != _MISMATCH
    assert reported in str(exc_info.value)
    assert not _rows_written(flow_repo, operation)


@pytest.mark.asyncio
async def test_save_without_changes_refuses_stored_steps_that_write_down(user):
    user.tenant.security_enabled = True
    # A flow stored with a default-input read of a classified step is refused on
    # its next save, even a rename that touches no step.
    service, flow_repo, flow = _classified_chain(
        user, [_HIGH_FIRST_STEP, _ClassifiedStep(model_level=1)]
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow(flow_id=flow.id, name="Renamed")

    assert exc_info.value.code == _MISMATCH
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_rejects_when_flow_is_published(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Published Flow",
        description="locked",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=1,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = source_flow

    with pytest.raises(BadRequestException, match="Cannot mutate a published flow"):
        await service.update_flow(flow_id=flow_id, name="new")


@pytest.mark.asyncio
async def test_update_flow_assistant_rejects_when_flow_published(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    published_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=2,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = published_flow

    with pytest.raises(
        BadRequestException, match="Cannot mutate assistant of a published flow"
    ):
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=uuid4(),
            update=AssistantUpdateCommand(name="Updated"),
        )


@pytest.mark.asyncio
async def test_create_flow_assistant_sets_flow_managed_origin(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = flow
    expected = _build_assistant(flow_id=flow_id, space_id=flow.space_id, user=user)
    assistant_service.create_assistant.return_value = (expected, [])

    assistant, _ = await service.create_flow_assistant(flow_id=flow_id, name="step")

    assert assistant.origin == AssistantOrigin.FLOW_MANAGED
    assistant_service.create_assistant.assert_awaited_once_with(
        name="step",
        space_id=flow.space_id,
        hidden=True,
        origin=AssistantOrigin.FLOW_MANAGED,
        managing_flow_id=flow_id,
    )


@pytest.mark.asyncio
async def test_get_flow_assistant_rejects_wrong_owner(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = flow
    wrong_owner_assistant = _build_assistant(
        flow_id=uuid4(),
        space_id=flow.space_id,
        user=user,
    )
    assistant_service.get_assistant.return_value = (wrong_owner_assistant, [])

    with pytest.raises(NotFoundException, match="belongs to a different flow"):
        await service.get_flow_assistant(
            flow_id=flow_id, assistant_id=wrong_owner_assistant.id
        )


@pytest.mark.asyncio
async def test_get_flow_assistant_rejects_non_flow_managed(user):
    """Assistant exists but is not flow-managed → clear error, not generic 404."""
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = flow

    # Assistant with origin != FLOW_MANAGED
    regular_assistant = _build_assistant(
        flow_id=flow_id, space_id=flow.space_id, user=user
    )
    regular_assistant.origin = AssistantOrigin.USER
    assistant_service.get_assistant.return_value = (regular_assistant, [])

    with pytest.raises(NotFoundException, match="not flow-managed"):
        await service.get_flow_assistant(
            flow_id=flow_id, assistant_id=regular_assistant.id
        )


@pytest.mark.asyncio
async def test_update_flow_assistant_passes_include_hidden(user):
    """update_flow_assistant must pass include_hidden=True to assistant_service."""
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    space_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=space_id,
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = flow

    owned_assistant = _build_assistant(flow_id=flow_id, space_id=space_id, user=user)
    assistant_service.get_assistant.return_value = (owned_assistant, [])
    assistant_service.update_assistant.return_value = (owned_assistant, [])

    update = AssistantUpdateCommand(name="Updated")
    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=owned_assistant.id,
        update=update,
    )

    assistant_service.update_assistant.assert_awaited_once_with(
        assistant_id=owned_assistant.id,
        update=update,
        caller=AssistantUpdateCaller.FLOW_MANAGED,
        include_hidden=True,
    )


@pytest.mark.asyncio
async def test_update_flow_assistant_explicit_none_forwards_completion_model_clear(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    space_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=space_id,
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = flow
    owned_assistant = _build_assistant(flow_id=flow_id, space_id=space_id, user=user)
    assistant_service.get_assistant.return_value = (owned_assistant, [])
    assistant_service.update_assistant.return_value = (owned_assistant, [])

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=owned_assistant.id,
        update=AssistantUpdateCommand(completion_model_id=None),
    )

    assert (
        "completion_model_id"
        in AssistantUpdateCommand(completion_model_id=None).model_fields_set
    )
    update = assistant_service.update_assistant.await_args.kwargs["update"]
    assert update.completion_model_id is None
    assert (
        assistant_service.update_assistant.await_args.kwargs["caller"]
        is AssistantUpdateCaller.FLOW_MANAGED
    )
    assert (
        assistant_service.update_assistant.await_args.kwargs["include_hidden"] is True
    )


@pytest.mark.asyncio
async def test_update_flow_assistant_forwards_every_command_field(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
    )

    flow_id = uuid4()
    space_id = uuid4()
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=space_id,
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[],
    )
    flow_repo.get.return_value = flow
    assistant = _build_assistant(flow_id=flow_id, space_id=space_id, user=user)
    assistant_service.get_assistant.return_value = (assistant, [])
    assistant_service.update_assistant.return_value = (assistant, [])

    model_id = uuid4()
    group_id = uuid4()
    website_id = uuid4()
    integration_id = uuid4()
    attachment_id = uuid4()
    icon_id = uuid4()
    model_kwargs = ModelKwargs(reasoning_effort="low")

    update = AssistantUpdateCommand(
        name="Updated",
        prompt=PromptCreate(text="Updated prompt"),
        completion_model_id=model_id,
        completion_model_kwargs=model_kwargs,
        logging_enabled=True,
        groups=[group_id],
        websites=[website_id],
        integration_knowledge_ids=[integration_id],
        attachments=[(attachment_id, True)],
        description=None,
        insight_enabled=True,
        data_retention_days=30,
        metadata_json={"source": "test"},
        icon_id=icon_id,
    )

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant.id,
        update=update,
    )

    assistant_service.update_assistant.assert_awaited_once_with(
        assistant_id=assistant.id,
        update=update,
        caller=AssistantUpdateCaller.FLOW_MANAGED,
        include_hidden=True,
    )


@pytest.mark.asyncio
async def test_update_flow_assistant_skips_security_validation_without_security_fields(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    space_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
        space_service=space_service,
    )

    flow_id = uuid4()
    step = _step(step_order=1)
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[step],
    )
    flow_repo.get.return_value = flow
    assistant = _build_assistant(flow_id=flow_id, space_id=flow.space_id, user=user)
    assistant.id = step.assistant_id
    assistant_service.get_assistant.return_value = (assistant, [])
    assistant_service.update_assistant.return_value = (assistant, [])

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant.id,
        update=AssistantUpdateCommand(name="Renamed"),
    )

    space_service.get_space.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_assistant_validates_explicit_security_field_set_to_none(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    space_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
        space_service=space_service,
    )

    flow_id = uuid4()
    step = _step(step_order=1)
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[step],
    )
    flow_repo.get.return_value = flow
    assistant = _build_assistant(flow_id=flow_id, space_id=flow.space_id, user=user)
    assistant.id = step.assistant_id
    assistant.completion_model = SimpleNamespace(
        security_classification=_classification(1),
        can_access=True,
    )
    assistant_service.get_assistant.return_value = (assistant, [])
    assistant_service.update_assistant.return_value = (assistant, [])
    space_service.get_space.return_value = _FlowSecuritySpaceStub()

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant.id,
        update=AssistantUpdateCommand(groups=None),
    )

    space_service.get_space.assert_awaited_once_with(flow.space_id)


@pytest.mark.asyncio
async def test_update_flow_assistant_prompt_edit_is_classified_like_the_writer(user):
    user.tenant.security_enabled = True
    # A valid chain: step 1 (assistant A, classified output 3) feeds step 2
    # (assistant B, level-1 model) through literal underlag only. A prompt
    # edit on B that starts reading step 1 must be rejected before the writer
    # runs; an unrelated prompt edit passes; and a null prompt keeps the stored
    # prompt exactly as Assistant.update does.
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    space_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
        space_service=space_service,
    )
    flow_id = uuid4()
    space_id = uuid4()
    strong = _build_assistant(flow_id=flow_id, space_id=space_id, user=user)
    strong.completion_model = SimpleNamespace(
        security_classification=_classification(3), can_access=True
    )
    weak = _build_assistant(flow_id=flow_id, space_id=space_id, user=user)
    weak.completion_model = SimpleNamespace(
        security_classification=_classification(1), can_access=True
    )
    assistants = {strong.id: strong, weak.id: weak}
    assistant_service.get_assistant.side_effect = lambda assistant_id: (
        assistants[assistant_id],
        [],
    )
    assistant_service.update_assistant.return_value = (weak, [])
    first = _step(step_order=1).model_copy(
        update={"assistant_id": strong.id, "output_classification_override": 3}
    )
    second = _step(step_order=2).model_copy(
        update={
            "assistant_id": weak.id,
            "input_source": "previous_step",
            "input_bindings": {"question": "Fast text."},
        }
    )
    flow_repo.get.return_value = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=space_id,
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[first, second],
    )
    low_model = SimpleNamespace(
        id=uuid4(), security_classification=_classification(1), can_access=True
    )
    space_service.get_space.return_value = _FlowSecuritySpaceStub(
        completion_models=[low_model]
    )

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=weak.id,
        update=AssistantUpdateCommand(prompt=PromptCreate(text="Skriv kort.")),
    )
    assert assistant_service.update_assistant.await_count == 1

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=weak.id,
            update=AssistantUpdateCommand(
                prompt=PromptCreate(text="Bakgrund: {{ step_1.output.text }}")
            ),
        )
    assert exc_info.value.code == "flow_step_security_classification_mismatch"
    assert assistant_service.update_assistant.await_count == 1

    # Stored prompt on B reads step 1; B's model is raised to 3 so the flow is
    # valid. A downgrade to the level-1 model with prompt=None must still see
    # the stored prompt.
    weak.completion_model = SimpleNamespace(
        security_classification=_classification(3), can_access=True
    )
    weak.prompt = SimpleNamespace(text="Bakgrund: {{ step_1.output.text }}")
    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=weak.id,
            update=AssistantUpdateCommand(
                completion_model_id=low_model.id, prompt=None
            ),
        )
    assert exc_info.value.code == "flow_step_security_classification_mismatch"
    assert assistant_service.update_assistant.await_count == 1


@pytest.mark.asyncio
async def test_update_flow_assistant_security_validation_accepts_model_clear(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    space_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
        space_service=space_service,
    )

    flow_id = uuid4()
    step = _step(step_order=1)
    flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[step],
    )
    flow_repo.get.return_value = flow
    assistant = _build_assistant(flow_id=flow_id, space_id=flow.space_id, user=user)
    assistant.id = step.assistant_id
    assistant.completion_model = SimpleNamespace(
        security_classification=_classification(1),
        can_access=True,
    )
    assistant_service.get_assistant.return_value = (assistant, [])
    assistant_service.update_assistant.return_value = (assistant, [])
    space_service.get_space.return_value = _FlowSecuritySpaceStub()

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant.id,
        update=AssistantUpdateCommand(completion_model_id=None),
    )

    space_service.get_space.assert_awaited_once_with(flow.space_id)


@pytest.mark.asyncio
async def test_update_flow_assistant_rejects_mcp_configuration(user):
    service = FlowService(
        user=user,
        flow_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        assistant_service=AsyncMock(),
    )

    with pytest.raises(BadRequestException, match="Flow MCP is unsupported"):
        await service.update_flow_assistant(
            flow_id=uuid4(),
            assistant_id=uuid4(),
            update=AssistantUpdateCommand(mcp_server_ids=[uuid4()]),
        )

    service.assistant_service.update_assistant.assert_not_awaited()
    service.flow_repo.advance_draft_revision.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_duplicate_step_names_case_insensitive(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    steps = [
        _step(step_order=1).model_copy(update={"user_description": "Sammanfattning"}),
        _step(step_order=2).model_copy(update={"user_description": "sammanfattning"}),
    ]

    with pytest.raises(BadRequestException, match="Step names must be unique"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=steps,
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_invalid_form_field_type(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException, match="must be one of"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Namn på brukare",
                            "type": "unsupported_type",
                            "required": True,
                        }
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_multiselect_without_options(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException, match="options must be a list"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Typ av insats",
                            "type": "multiselect",
                            "required": True,
                        }
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_options_for_non_multiselect(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(
        BadRequestException, match="only valid for select or multiselect"
    ):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Personnummer",
                            "type": "text",
                            "required": True,
                            "options": ["x"],
                        }
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_create_flow_normalizes_legacy_form_field_types(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[_step()],
        metadata_json={
            "form_schema": {
                "fields": [
                    {"name": "Email", "type": "email", "required": True},
                    {"name": "Anteckning", "type": "textarea", "required": False},
                ]
            },
            "wizard": {"transcription_enabled": True},
            "ai_builder": {"origin": _ai_builder_origin_metadata()},
        },
    )

    field_types = [
        field["type"] for field in created.metadata_json["form_schema"]["fields"]
    ]
    assert field_types == ["text", "text"]
    assert created.metadata_json["wizard"] == {"transcription_enabled": True}
    assert "origin" in created.metadata_json["ai_builder"]


@pytest.mark.asyncio
async def test_create_flow_rejects_unknown_metadata_bucket(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(
        BadRequestException,
        match="metadata_json contains unknown top-level fields: transcription",
    ):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={"transcription": {"language": "sv"}},
        )
    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_without_metadata_normalizes_existing_metadata_tolerantly(
    user,
):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    flow_id = uuid4()
    source_flow = Flow(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json={
            "form_schema": {
                "fields": [{"name": "case_id", "type": "string", "required": "yes"}]
            },
            "ai_builder": {"description": "Generated draft"},
        },
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = source_flow
    flow_repo.update.side_effect = lambda flow, tenant_id, **_: flow

    updated = await service.update_flow(flow_id=flow_id, name="Updated")

    assert updated.metadata_json == {
        "form_schema": {
            "fields": [{"name": "case_id", "type": "text", "required": False}]
        }
    }


@pytest.mark.asyncio
async def test_create_flow_allows_scalar_runtime_reserved_form_field_names(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[_step()],
        metadata_json={
            "form_schema": {
                "fields": [{"name": "datum", "type": "date", "required": True}]
            }
        },
    )

    assert created.metadata_json["form_schema"]["fields"][0]["name"] == "datum"


@pytest.mark.asyncio
async def test_create_flow_rejects_form_field_name_conflicting_with_step_name(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException, match="conflicts with form field name"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[
                _step(step_order=1).model_copy(
                    update={"user_description": "Sammanfattning"}
                ),
                _step(step_order=2).model_copy(update={"user_description": "Analys"}),
            ],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "Sammanfattning", "type": "text", "required": True}
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_publish_flow_rejects_unencrypted_stored_http_secret(user):
    """Publishing copies stored config into an immutable version."""
    stored = _published_flow_for_update(
        user, [_http_step_with_token("legacy-plaintext-secret")]
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    version_repo = AsyncMock()
    flow_repo.allocate_next_version.return_value = 1
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_FakeEncryptionService(),
    )

    with pytest.raises(BadRequestException) as excinfo:
        await service.publish_flow(flow_id=stored.id)

    assert "ENCRYPTION_KEY" in str(excinfo.value)
    assert "legacy-plaintext-secret" not in str(excinfo.value)
    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_flow_rejects_stored_secret_the_key_cannot_decrypt(user):
    """A row written before encryption can hold a typed prefix-shaped literal."""

    class _RejectingEncryptionService(_FakeEncryptionService):
        def can_decrypt(self, value: str) -> bool:
            return False

    stored = _published_flow_for_update(
        user, [_http_step_with_token("enc:not-really-ciphertext")]
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    version_repo = AsyncMock()
    flow_repo.allocate_next_version.return_value = 1
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_RejectingEncryptionService(),
    )

    with pytest.raises(BadRequestException):
        await service.publish_flow(flow_id=stored.id)

    version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_flow_allows_encrypted_stored_http_secret(user):
    stored = _published_flow_for_update(
        user, [_http_step_with_token("enc:stored-secret")]
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = stored
    flow_repo.update.side_effect = lambda flow, **kwargs: flow
    version_repo = AsyncMock()
    flow_repo.allocate_next_version.return_value = 1
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=_FakeEncryptionService(),
    )

    await service.publish_flow(flow_id=stored.id)

    version_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_drops_inactive_config_before_secret_validation(user):
    repo = AsyncMock()
    repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(user=user, flow_repo=repo, version_repo=AsyncMock())
    step = _step().model_copy(
        update={
            "input_config": {"url": "obsolete", "auth": "malformed"},
            "output_config": {
                "template_file_id": "obsolete",
                "custom_headers": [{"value": SECRET_SENTINEL}],
                "extension": "preserved",
            },
        }
    )
    created = await service.create_flow(space_id=uuid4(), name="Flow", steps=[step])
    assert created.steps[0].input_config is None
    assert created.steps[0].output_config == {"extension": "preserved"}
    assert step.input_config == {"url": "obsolete", "auth": "malformed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("supply_steps", [True, False])
async def test_update_flow_drops_inactive_stored_credentials(user, supply_steps):
    repo = AsyncMock()
    stored_step = _step().model_copy(
        update={"input_config": _http_authored_config("enc:stored-credential")}
    )
    existing = _published_flow_for_update(user, [stored_step])
    repo.get.return_value = existing
    repo.update.side_effect = lambda flow, tenant_id, expected_revision=None: flow
    service = _service(user=user, flow_repo=repo, version_repo=AsyncMock())
    incoming = stored_step.model_copy(
        update={"input_config": _http_authored_config(SECRET_SENTINEL)}
    )
    new_step = _step(2).model_copy(
        update={"id": None, "input_config": _http_authored_config(SECRET_SENTINEL)}
    )
    updated = await service.update_flow(
        flow_id=existing.id,
        steps=[incoming, new_step] if supply_steps else None,
    )
    assert all(step.input_config is None for step in updated.steps)
