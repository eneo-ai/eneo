from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant, AssistantOrigin
from intric.flows.flow import Flow, FlowStep, FlowVersion
from intric.flows.flow_service import FlowService
from intric.main.models import NOT_PROVIDED
from intric.main.exceptions import BadRequestException, NotFoundException


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


def _service(*, user, flow_repo, version_repo, encryption_service=None) -> FlowService:
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
        encryption_service=encryption_service,
    )
    service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    return service


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
    flow_repo.update.return_value = source_flow.model_copy(update={"published_version": 1})
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
            )
        ],
    )
    flow_repo.get.return_value = source_flow
    version_repo.get_latest.return_value = None
    flow_repo.update.return_value = source_flow.model_copy(update={"published_version": 1})
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
        _step(step_order=1).model_copy(
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
    flow_repo.update.return_value = source_flow.model_copy(update={"published_version": 1})
    _stub_template_asset_lookup(
        service,
        flow_id=flow_id,
        file_id=template_file_id,
    )
    service._inspect_docx_template = MagicMock(  # type: ignore[attr-defined]
        return_value=[{"name": "optional_section", "location": "body", "preview": "{{optional_section}}"}]
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
async def test_create_flow_encrypts_step_header_values(user):
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
            "input_config": {"url": "https://example.org/input", "headers": {"Authorization": "Bearer topsecret"}},
            "output_config": {"url": "https://example.org/output", "headers": {"X-Api-Key": "abc123"}},
        }
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    assert created.steps[0].input_config["headers"]["Authorization"] == "enc:Bearer topsecret"
    assert created.steps[0].output_config["headers"]["X-Api-Key"] == "enc:abc123"


@pytest.mark.asyncio
async def test_create_flow_rejects_header_secrets_without_encryption_key(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=None,
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_config": {
                "url": "https://example.org/input",
                "headers": {"Authorization": "Bearer topsecret"},
            }
        }
    )

    with pytest.raises(BadRequestException, match="ENCRYPTION_KEY"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[step],
            metadata_json=None,
        )


@pytest.mark.asyncio
async def test_create_flow_allows_empty_headers_without_encryption_key(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        encryption_service=None,
    )
    step = _step(step_order=1).model_copy(
        update={
            "input_config": {
                "url": "https://example.org/input",
                "headers": {},
            }
        }
    )

    created = await service.create_flow(
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        metadata_json=None,
    )

    assert created.steps[0].input_config["headers"] == {}


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
            "input_config": {"url": "https://example.org/source", "timeout_seconds": 12},
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
            "input_config": {"timeout_seconds": 5},
        }
    )

    with pytest.raises(BadRequestException, match="input_config.url"):
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
            "input_config": {"url": "https://example.org/source", "timeout_seconds": 0},
        }
    )

    with pytest.raises(BadRequestException, match="timeout_seconds"):
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
            "output_config": {},
        }
    )

    with pytest.raises(BadRequestException, match="output_config.url"):
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
                "timeout_seconds": 25,
                "body_template": '{"message":"{{flow_input.text}}"}',
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

    allowed_result = MagicMock()
    allowed_result.all.return_value = []
    flow_repo.session = AsyncMock()
    flow_repo.session.execute.return_value = allowed_result

    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=version_repo,
        assistant_service=AsyncMock(),
        file_repo=AsyncMock(),
        template_asset_repo=AsyncMock(),
    )

    with pytest.raises(BadRequestException, match="outside the selected space or tenant"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step(step_order=1)],
            metadata_json=None,
        )


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

    with pytest.raises(BadRequestException, match="Cannot mutate assistant of a published flow"):
        await service.update_flow_assistant(
            flow_id=flow_id,
            assistant_id=uuid4(),
            name="Updated",
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
        await service.get_flow_assistant(flow_id=flow_id, assistant_id=wrong_owner_assistant.id)


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
    regular_assistant = _build_assistant(flow_id=flow_id, space_id=flow.space_id, user=user)
    regular_assistant.origin = AssistantOrigin.USER
    assistant_service.get_assistant.return_value = (regular_assistant, [])

    with pytest.raises(NotFoundException, match="not flow-managed"):
        await service.get_flow_assistant(flow_id=flow_id, assistant_id=regular_assistant.id)


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
        name="Updated",
    )

    assistant_service.update_assistant.assert_awaited_once_with(
        assistant_id=owned_assistant.id,
        include_hidden=True,
        name="Updated",
    )


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
                        {"name": "Namn på brukare", "type": "unsupported_type", "required": True}
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
                        {"name": "Typ av insats", "type": "multiselect", "required": True}
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_options_for_non_multiselect(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException, match="only valid for select or multiselect"):
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
            }
        },
    )

    field_types = [field["type"] for field in created.metadata_json["form_schema"]["fields"]]
    assert field_types == ["text", "text"]


@pytest.mark.asyncio
async def test_create_flow_rejects_reserved_form_field_alias_names(user):
    flow_repo = AsyncMock()
    version_repo = AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)

    with pytest.raises(BadRequestException, match="reserved"):
        await service.create_flow(
            space_id=uuid4(),
            name="Flow",
            steps=[_step()],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "flow_input", "type": "text", "required": True}
                    ]
                }
            },
        )


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
                _step(step_order=1).model_copy(update={"user_description": "Sammanfattning"}),
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
