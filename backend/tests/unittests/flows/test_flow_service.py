from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant, AssistantOrigin
from intric.flows.application.flow_assistant_update import FlowAssistantUpdateCommand
from intric.flows.application.flow_service import FlowService
from intric.flows.assistant_execution_snapshot import stable_hash
from intric.flows.domain.flow import Flow, FlowStep, FlowVersion
from intric.flows.domain.flow_invariant_exceptions import (
    FlowPersistedIdMissingError,
    FlowPublishedDefinitionInvalidError,
)
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from intric.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from intric.flows.http_transport import SECRET_SENTINEL
from intric.main.exceptions import BadRequestException, NotFoundException
from intric.main.models import NOT_PROVIDED
from intric.prompts.api.prompt_models import PromptCreate


class _FakeEncryptionService:
    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith("enc:")

    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext}"

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
        mcp_policy="inherit",
    )


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
    def __init__(
        self, *, level: int | None = None, mcp_servers=None, completion_models=None
    ):
        self.security_classification = (
            _classification(level) if level is not None else None
        )
        self._mcp_servers = {server.id: server for server in (mcp_servers or [])}
        self._completion_models = {
            model.id: model for model in (completion_models or [])
        }

    def get_mcp_server(self, server_id):
        if server_id not in self._mcp_servers:
            raise NotFoundException()
        return self._mcp_servers[server_id]

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
    blob: bytes | None = b"template-bytes",
):
    resolved_asset_id = asset_id or uuid4()
    asset = SimpleNamespace(
        id=resolved_asset_id,
        flow_id=flow_id,
        file_id=file_id,
        name=name,
        checksum=checksum,
    )
    service.template_asset_repo.get_by_flow_file.return_value = asset
    service.template_asset_repo.get.return_value = asset
    service.file_repo.get_by_id.return_value = SimpleNamespace(
        id=file_id,
        checksum=checksum,
        name=name,
        tenant_id=service.user.tenant_id,
        blob=blob,
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        encryption_service=encryption_service,
        space_service=space_service,
    )
    if stub_assistant_scope:
        service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    service.assistant_service.get_assistant.return_value = (
        SimpleNamespace(mcp_servers=[]),
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
    template_file_id = uuid4()
    step = _step(step_order=1).model_copy(
        update={
            "output_mode": "template_fill",
            "output_type": "docx",
            "output_config": {"template_file_id": str(template_file_id)},
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

    service.template_asset_repo.get_by_flow_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_flows_passes_published_only_to_sparse_repo_path(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.get_sparse_by_space.return_value = []
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    space_id = uuid4()

    await service.list_flows(
        space_id=space_id,
        sparse=True,
        published_only=True,
        limit=25,
        offset=10,
    )

    flow_repo.get_sparse_by_space.assert_awaited_once_with(
        space_id=space_id,
        tenant_id=user.tenant_id,
        published_only=True,
        limit=25,
        offset=10,
    )


@pytest.mark.asyncio
async def test_list_flows_passes_published_only_to_full_repo_path(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.get_by_space.return_value = []
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    space_id = uuid4()

    await service.list_flows(
        space_id=space_id,
        sparse=False,
        published_only=True,
        limit=5,
        offset=0,
    )

    flow_repo.get_by_space.assert_awaited_once_with(
        space_id=space_id,
        tenant_id=user.tenant_id,
        published_only=True,
        limit=5,
        offset=0,
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
    latest_version = None
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
    version_repo.get_latest.return_value = latest_version
    version_repo.create.return_value = created_version
    flow_repo.update.return_value = updated_flow

    result = await service.publish_flow(flow_id=flow_id)

    assert result.published_version == 1
    version_repo.create.assert_awaited_once()
    flow_repo.update.assert_awaited_once()
    assert flow_repo.update.await_args.kwargs["expected_revision"] == 7


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
    version_repo.get_latest.return_value = None

    with pytest.raises(FlowPublishedDefinitionInvalidError) as exc_info:
        await service.publish_flow(flow_id=flow_id)

    assert exc_info.value.flow_id == flow_id
    assert exc_info.value.flow_version == 1
    assert exc_info.value.parser_code == "flow_version_missing_step_identifiers"
    assert exc_info.value.parser_context == {"step_order": 1}
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
            "ai_builder": {"description": "Generated draft"},
        },
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = flow
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["metadata_json"] == {
        "form_schema": {"fields": [{"name": "case_id", "type": "text"}]},
        "care_data_policy": {"sensitive": False},
        "ai_builder": {"description": "Generated draft"},
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
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["steps"][0]["review_policy"] == {"mode": "view"}


@pytest.mark.asyncio
async def test_publish_flow_includes_mcp_snapshot_fields(user):
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
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = flow.model_copy(update={"published_version": 1})
    model_id = uuid4()
    tool_schema = {"type": "object", "properties": {"city": {"type": "string"}}}
    service.assistant_service.get_assistant.return_value = (
        SimpleNamespace(
            id=step.assistant_id,
            origin=AssistantOrigin.FLOW_MANAGED,
            managing_flow_id=flow_id,
            prompt=SimpleNamespace(text="Use the weather tool only when needed."),
            completion_model=SimpleNamespace(
                id=model_id,
                name="gpt-5.4-nano",
                nickname="Nano",
                litellm_model_name="openai/gpt-5.4-nano",
            ),
            completion_model_kwargs=ModelKwargs(temperature=0.2),
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
                            description="Fetches a forecast by city.",
                            input_schema=tool_schema,
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

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["schema_version"] == 1
    assert definition["steps"][0]["mcp_servers"] == [
        {
            "id": str(
                service.assistant_service.get_assistant.return_value[0]
                .mcp_servers[0]
                .id
            ),
            "name": "Weather Server",
        }
    ]
    assert definition["steps"][0]["mcp_tools_enabled"] == [
        {
            "tool_id": str(
                service.assistant_service.get_assistant.return_value[0]
                .mcp_servers[0]
                .tools[0]
                .id
            ),
            "server_id": str(
                service.assistant_service.get_assistant.return_value[0]
                .mcp_servers[0]
                .id
            ),
            "name": "forecast_tool",
        }
    ]
    snapshot = definition["steps"][0]["assistant_snapshot"]
    assert snapshot["schema_version"] == 1
    assert snapshot["assistant_id"] == str(step.assistant_id)
    assert snapshot["origin"] == "flow_managed"
    assert snapshot["instructions"] == "Use the weather tool only when needed."
    assert snapshot["completion_model"] == {
        "id": str(model_id),
        "name": "gpt-5.4-nano",
        "nickname": "Nano",
        "litellm_model_name": "openai/gpt-5.4-nano",
    }
    assert snapshot["completion_model_kwargs"] == {"temperature": 0.2}
    assert snapshot["knowledge_refs"] == []
    assert snapshot["mcp_tools"][0] == {
        "tool_id": str(
            service.assistant_service.get_assistant.return_value[0]
            .mcp_servers[0]
            .tools[0]
            .id
        ),
        "server_id": str(
            service.assistant_service.get_assistant.return_value[0].mcp_servers[0].id
        ),
        "server_name": "Weather Server",
        "name": "forecast_tool",
        "description": "Fetches a forecast by city.",
        "input_schema": tool_schema,
        "input_schema_hash": stable_hash(tool_schema),
    }
    assert snapshot["tool_surface_hash"] == stable_hash(snapshot["mcp_tools"])
    assert snapshot["execution_surface_hash"] == stable_hash(
        {
            "schema_version": 1,
            "assistant_id": str(step.assistant_id),
            "instructions": "Use the weather tool only when needed.",
            "completion_model": {
                "id": str(model_id),
                "litellm_model_name": "openai/gpt-5.4-nano",
            },
            "completion_model_kwargs": {"temperature": 0.2},
            "knowledge_refs": [],
            "mcp_tools": [
                {
                    "tool_id": str(
                        service.assistant_service.get_assistant.return_value[0]
                        .mcp_servers[0]
                        .tools[0]
                        .id
                    ),
                    "server_id": str(
                        service.assistant_service.get_assistant.return_value[0]
                        .mcp_servers[0]
                        .id
                    ),
                    "server_name": "Weather Server",
                    "name": "forecast_tool",
                    "description": "Fetches a forecast by city.",
                    "input_schema_hash": stable_hash(tool_schema),
                }
            ],
        }
    )


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
            "input_config": _http_authored_config("enc:first-secret"),
        },
        deep=True,
    )
    second_step = _step(step_order=2).model_copy(
        update={
            "input_source": "previous_step",
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
            "input_source": "previous_step",
            "input_config": _http_authored_config(SECRET_SENTINEL),
        },
        deep=True,
    )
    second_incoming = second_step.model_copy(
        update={
            "step_order": 1,
            "input_source": "flow_input",
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
            "input_source": "previous_step",
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
                        "template_file_id": str(template_file_id),
                        "bindings": {"section": "{{flow_input.title}}"},
                    },
                }
            )
        ],
    )
    flow_repo.get.return_value = source_flow
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = source_flow.model_copy(
        update={"published_version": 1}
    )
    asset = _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
    )
    service._inspect_docx_template = MagicMock(  # type: ignore[attr-defined]
        return_value=[{"name": "section", "location": "body", "preview": "{{section}}"}]
    )

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    output_config = definition["steps"][0]["output_config"]
    assert output_config["template_asset_id"] == str(asset.id)
    assert output_config["template_file_id"] == str(template_file_id)
    assert output_config["template_checksum"] == "abc123"
    assert output_config["template_name"] == "rapport.docx"
    assert output_config["placeholders"] == ["section"]


@pytest.mark.asyncio
async def test_publish_flow_preserves_template_placeholder_order(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
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
                        "template_file_id": str(template_file_id),
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
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = source_flow.model_copy(
        update={"published_version": 1}
    )
    _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
    )
    service._inspect_docx_template = MagicMock(  # type: ignore[attr-defined]
        return_value=[
            {"name": "bakgrund", "location": "body", "preview": "{{bakgrund}}"},
            {"name": "analys", "location": "body", "preview": "{{analys}}"},
            {"name": "slutsats", "location": "body", "preview": "{{slutsats}}"},
        ]
    )

    await service.publish_flow(flow_id=flow_id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    output_config = definition["steps"][1]["output_config"]
    assert output_config["placeholders"] == ["bakgrund", "analys", "slutsats"]


@pytest.mark.asyncio
async def test_get_owned_docx_template_file_reports_missing_blob_clearly(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    file_id = uuid4()
    asset = _stub_template_asset_lookup(
        service,
        flow_id=uuid4(),
        file_id=file_id,
        name="template.docx",
        blob=None,
    )

    with pytest.raises(
        BadRequestException,
        match="could not be read because the file content is missing",
    ):
        await service._get_template_asset_file(flow_id=asset.flow_id, asset_id=asset.id)


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
async def test_publish_flow_rejects_empty_template_bindings(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
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
                        "template_file_id": str(template_file_id),
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
    )
    service._inspect_docx_template = MagicMock(  # type: ignore[attr-defined]
        return_value=[{"name": "section", "location": "body", "preview": "{{section}}"}]
    )

    with pytest.raises(BadRequestException, match="missing bindings"):
        await service.publish_flow(flow_id=flow_id)


@pytest.mark.asyncio
async def test_publish_flow_allows_explicit_empty_template_binding(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    flow_id = uuid4()
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
                        "template_file_id": str(template_file_id),
                        "bindings": {"optional_section": ""},
                    },
                }
            )
        ],
    )
    flow_repo.get.return_value = source_flow
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = source_flow.model_copy(
        update={"published_version": 1}
    )
    _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
    )
    service._inspect_docx_template = MagicMock(  # type: ignore[attr-defined]
        return_value=[
            {
                "name": "optional_section",
                "location": "body",
                "preview": "{{optional_section}}",
            }
        ]
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
        update={"input_bindings": {"value": "{{step_1.output.summary}}"}}
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
async def test_create_flow_rejects_http_post_input_invalid_timeout(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    step = _step(step_order=1).model_copy(
        update={
            "input_source": "http_post",
            "input_config": {
                "url": "https://example.org/source",
                "auth": {"mode": "none"},
                "timeout_seconds": 0,
            },
        }
    )

    with pytest.raises(BadRequestException, match="HTTP_TIMEOUT_OUT_OF_RANGE"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )


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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException,
        match="Flow steps must reference flow-managed assistants owned by the flow",
    ):
        await service.publish_flow(flow_id=flow_id)


@pytest.mark.asyncio
async def test_publish_flow_rejects_assistant_model_below_required_security_level(user):
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        space_service=AsyncMock(),
    )
    service.space_service.get_space.return_value = SimpleNamespace(
        security_classification=SimpleNamespace(security_level=3)
    )
    service.assistant_service.get_assistant.return_value = (
        SimpleNamespace(
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
async def test_publish_flow_rejects_output_override_write_down(user):
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
                    "input_source": "previous_step",
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        space_service=AsyncMock(),
    )
    service.space_service.get_space.return_value = SimpleNamespace(
        security_classification=SimpleNamespace(security_level=1)
    )
    service.assistant_service.get_assistant.side_effect = [
        (
            SimpleNamespace(
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
            update=FlowAssistantUpdateCommand(name="Updated"),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        update=FlowAssistantUpdateCommand(name="Updated"),
    )

    assistant_service.update_assistant.assert_awaited_once_with(
        assistant_id=owned_assistant.id,
        include_hidden=True,
        name="Updated",
        prompt=None,
        completion_model_id=NOT_PROVIDED,
        completion_model_kwargs=None,
        logging_enabled=None,
        groups=None,
        websites=None,
        integration_knowledge_ids=None,
        mcp_server_ids=None,
        mcp_tools=None,
        attachment_ids=None,
        description=NOT_PROVIDED,
        insight_enabled=None,
        data_retention_days=NOT_PROVIDED,
        metadata_json=NOT_PROVIDED,
        icon_id=NOT_PROVIDED,
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        update=FlowAssistantUpdateCommand(completion_model_id=None),
    )

    assert (
        "completion_model_id"
        in FlowAssistantUpdateCommand(completion_model_id=None).model_fields_set
    )
    assert (
        assistant_service.update_assistant.await_args.kwargs["completion_model_id"]
        is None
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
    server_id = uuid4()
    tool_id = uuid4()
    attachment_id = uuid4()
    icon_id = uuid4()
    model_kwargs = ModelKwargs(reasoning_effort="low")

    update = FlowAssistantUpdateCommand(
        name="Updated",
        prompt=PromptCreate(text="Updated prompt"),
        completion_model_id=model_id,
        completion_model_kwargs=model_kwargs,
        logging_enabled=True,
        groups=[group_id],
        websites=[website_id],
        integration_knowledge_ids=[integration_id],
        mcp_server_ids=[server_id],
        mcp_tools=[(tool_id, False)],
        attachment_ids=[attachment_id],
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
        include_hidden=True,
        name="Updated",
        prompt=update.prompt,
        completion_model_id=model_id,
        completion_model_kwargs=model_kwargs,
        logging_enabled=True,
        groups=[group_id],
        websites=[website_id],
        integration_knowledge_ids=[integration_id],
        mcp_server_ids=[server_id],
        mcp_tools=[(tool_id, False)],
        attachment_ids=[attachment_id],
        description=None,
        insight_enabled=True,
        data_retention_days=30,
        metadata_json={"source": "test"},
        icon_id=icon_id,
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        update=FlowAssistantUpdateCommand(name="Renamed"),
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        update=FlowAssistantUpdateCommand(groups=None),
    )

    space_service.get_space.assert_awaited_once_with(flow.space_id)


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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
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
        update=FlowAssistantUpdateCommand(completion_model_id=None),
    )

    space_service.get_space.assert_awaited_once_with(flow.space_id)


@pytest.mark.asyncio
async def test_update_flow_assistant_rejects_step_incompatible_mcp_server(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    space_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        space_service=space_service,
    )

    flow_id = uuid4()
    step_one = _step(step_order=1).model_copy(
        update={"output_classification_override": 3}
    )
    step_two = _step(step_order=2).model_copy(update={"input_source": "previous_step"})
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
        steps=[step_one, step_two],
    )
    flow_repo.get.return_value = flow

    first_assistant = _build_assistant(
        flow_id=flow_id, space_id=flow.space_id, user=user
    )
    first_assistant.id = step_one.assistant_id
    first_assistant.completion_model = SimpleNamespace(
        security_classification=_classification(3),
        can_access=True,
    )
    second_assistant = _build_assistant(
        flow_id=flow_id, space_id=flow.space_id, user=user
    )
    second_assistant.id = step_two.assistant_id
    second_assistant.completion_model = SimpleNamespace(
        security_classification=_classification(3),
        can_access=True,
    )
    low_server = SimpleNamespace(id=uuid4(), security_classification=_classification(2))
    space_service.get_space.return_value = _FlowSecuritySpaceStub(
        level=1,
        mcp_servers=[low_server],
    )
    assistant_service.get_assistant.side_effect = [
        (second_assistant, []),
        (first_assistant, []),
    ]

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=second_assistant.id,
            update=FlowAssistantUpdateCommand(mcp_server_ids=[low_server.id]),
        )

    assert exc_info.value.code == "flow_step_mcp_security_classification_mismatch"
    assistant_service.update_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_assistant_rejects_unavailable_mcp_server(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    assistant_service = AsyncMock()
    space_service = AsyncMock()
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=assistant_service,
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        space_service=space_service,
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
        steps=[_step(step_order=1)],
    )
    flow_repo.get.return_value = flow

    assistant = _build_assistant(flow_id=flow_id, space_id=flow.space_id, user=user)
    assistant.id = flow.steps[0].assistant_id
    assistant.completion_model = SimpleNamespace(
        security_classification=_classification(3),
        can_access=True,
    )
    assistant_service.get_assistant.return_value = (assistant, [])
    space_service.get_space.return_value = _FlowSecuritySpaceStub(
        level=1,
        mcp_servers=[],
    )
    unavailable_server_ids = [uuid4(), uuid4()]

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=assistant.id,
            update=FlowAssistantUpdateCommand(mcp_server_ids=unavailable_server_ids),
        )

    assert exc_info.value.code == "flow_mcp_server_not_available"
    assert exc_info.value.context == {
        "mcp_server_ids": [str(server_id) for server_id in unavailable_server_ids]
    }
    assistant_service.update_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_assistant_rejects_changes_that_invalidate_downstream_steps(
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        space_service=space_service,
    )

    flow_id = uuid4()
    step_one = _step(step_order=1)
    step_two = _step(step_order=2).model_copy(update={"input_source": "previous_step"})
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
        steps=[step_one, step_two],
    )
    flow_repo.get.return_value = flow

    first_assistant = _build_assistant(
        flow_id=flow_id, space_id=flow.space_id, user=user
    )
    first_assistant.id = step_one.assistant_id
    first_assistant.completion_model = SimpleNamespace(
        security_classification=_classification(3),
        can_access=True,
    )
    second_assistant = _build_assistant(
        flow_id=flow_id, space_id=flow.space_id, user=user
    )
    second_assistant.id = step_two.assistant_id
    second_assistant.completion_model = SimpleNamespace(
        security_classification=_classification(3),
        can_access=True,
    )
    second_assistant.mcp_servers = [
        SimpleNamespace(id=uuid4(), security_classification=_classification(2))
    ]
    high_server = SimpleNamespace(
        id=uuid4(), security_classification=_classification(3)
    )
    space_service.get_space.return_value = _FlowSecuritySpaceStub(
        level=1,
        mcp_servers=[high_server],
    )
    assistant_service.get_assistant.side_effect = [
        (first_assistant, []),
        (second_assistant, []),
    ]

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=first_assistant.id,
            update=FlowAssistantUpdateCommand(mcp_server_ids=[high_server.id]),
        )

    assert exc_info.value.code == "flow_step_mcp_security_classification_mismatch"
    assistant_service.update_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_flow_assistant_current_step_output_override_does_not_raise_same_step_mcp_floor(
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
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        space_service=space_service,
    )

    flow_id = uuid4()
    step = _step(step_order=1).model_copy(update={"output_classification_override": 3})
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
        security_classification=_classification(3),
        can_access=True,
    )
    low_server = SimpleNamespace(id=uuid4(), security_classification=_classification(1))
    space_service.get_space.return_value = _FlowSecuritySpaceStub(
        level=None,
        mcp_servers=[low_server],
    )
    assistant_service.get_assistant.return_value = (assistant, [])
    assistant_service.update_assistant.return_value = (assistant, [])

    await service.update_flow_assistant(
        flow_id=flow_id,
        assistant_id=assistant.id,
        update=FlowAssistantUpdateCommand(mcp_server_ids=[low_server.id]),
    )

    assistant_service.update_assistant.assert_awaited_once()


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
            "ai_builder": {"description": "Generated draft"},
            "transcription": {"language": "sv"},
        },
    )

    field_types = [
        field["type"] for field in created.metadata_json["form_schema"]["fields"]
    ]
    assert field_types == ["text", "text"]
    assert created.metadata_json["ai_builder"] == {"description": "Generated draft"}
    assert created.metadata_json["transcription"] == {"language": "sv"}


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
        },
        "ai_builder": {"description": "Generated draft"},
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
