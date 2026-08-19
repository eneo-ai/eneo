from __future__ import annotations

import io
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from docx import Document
from sqlalchemy.exc import DBAPIError, IntegrityError

from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    BuilderSessionFiles,
    BuilderSessions,
    FlowTemplateAssets,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_protocol import PendingFileContent, PreparedFileUpload
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.application.flow_authoring_command import TemplateAttachmentIntent
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftStepChangeKind,
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_template_attachment_materialization import (
    materialize_template_attachment,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import FlowResourceBindingSource
from eneo.flows.flow_template_asset_service import (
    AttachedTemplateFileUnavailableError,
)
from eneo.main.exceptions import BadRequestException

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _template_bytes(placeholder: str) -> bytes:
    document = Document()
    document.add_paragraph("{{ " + placeholder + " }}")
    payload = io.BytesIO()
    document.save(payload)
    return payload.getvalue()


async def _bytes(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


async def _save_template_file(container, *, name: str, content: bytes):
    return await container.file_service().save_prepared_file(
        PreparedFileUpload(
            name=name,
            file_type=FileType.DOCUMENT,
            display_media_type=DOCX_MIME,
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes(content),
                    declared_media_type=DOCX_MIME,
                    verified_media_type=DOCX_MIME,
                ),
            ),
        )
    )


def _template_changeset():
    spec = FlowDraftSpecCore(
        flow_name="Template flow",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Prepare",
                assistant_spec=AssistantSpec(instructions="Prepare content."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Fill",
                assistant_spec=AssistantSpec(instructions="Fill template."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
                output_config={"bindings": {"case_id": "{{ flow_input.case_id }}"}},
            ),
        ],
    )
    return compile_flow_draft_changeset(spec, current_flow=None)


async def _create_flow_and_file(container, *, placeholder: str):
    user = container.user()
    space = Spaces(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=f"template-binding-{uuid4().hex}",
    )
    container.session().add(space)
    await container.session().flush()
    flow = await container.flow_service().create_flow(
        space_id=space.id,
        name=f"Template flow {uuid4().hex}",
        description="",
        steps=[],
    )
    content = _template_bytes(placeholder)
    file = await _save_template_file(
        container,
        name="template.docx",
        content=content,
    )
    return user, space, flow, file


async def _delete_file(
    *,
    file_id,
    lock_timeout: bool,
) -> None:
    async with sessionmanager.session() as session, session.begin():
        if lock_timeout:
            await session.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
        await session.execute(sa.delete(Files).where(Files.id == file_id))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_promoted_template_survives_builder_session_deletion_and_fences_file(
    db_container,
) -> None:
    async with db_container() as setup_container:
        user, space, flow, file = await _create_flow_and_file(
            setup_container,
            placeholder="case_id",
        )
        repo = AIBuilderRepository(setup_container.session())
        builder_session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space.id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
        )
        await setup_container.session().execute(
            sa.insert(BuilderSessionFiles).values(
                session_id=builder_session.id,
                file_id=file.id,
                tenant_id=user.tenant_id,
            )
        )

    async with db_container(user=user) as container:
        asset = await container.flow_template_asset_service().create_from_existing_attached_file(
            flow_id=flow.id,
            file_id=file.id,
        )
        await container.session().execute(
            sa.delete(BuilderSessions).where(BuilderSessions.id == builder_session.id)
        )
        await container.session().flush()

        persisted_asset_file_id = await container.session().scalar(
            sa.select(FlowTemplateAssets.file_id).where(
                FlowTemplateAssets.id == asset.id
            )
        )
        persisted_file_id = await container.session().scalar(
            sa.select(Files.id).where(Files.id == file.id)
        )
        assert persisted_asset_file_id == file.id
        assert persisted_file_id == file.id

        with pytest.raises(IntegrityError):
            async with container.session().begin_nested():
                await container.session().execute(
                    sa.delete(Files).where(Files.id == file.id)
                )
                await container.session().flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_template_promotion_lock_serializes_both_file_delete_race_orders(
    db_container,
) -> None:
    async with db_container() as setup_container:
        user, _space, flow, file = await _create_flow_and_file(
            setup_container,
            placeholder="case_id",
        )

    async with db_container(user=user) as promotion_container:
        asset = await promotion_container.flow_template_asset_service().create_from_existing_attached_file(
            flow_id=flow.id,
            file_id=file.id,
        )
        with pytest.raises(DBAPIError) as lock_error:
            await _delete_file(file_id=file.id, lock_timeout=True)
        assert getattr(lock_error.value.orig, "sqlstate", None) == "55P03"
        assert asset.file_id == file.id

    with pytest.raises(IntegrityError):
        await _delete_file(file_id=file.id, lock_timeout=False)

    async with db_container(user=user) as setup_container:
        second_content = _template_bytes("reference_number")
        second_file = await _save_template_file(
            setup_container,
            name="second-template.docx",
            content=second_content,
        )
    await _delete_file(file_id=second_file.id, lock_timeout=False)

    async with db_container(user=user) as promotion_container:
        with pytest.raises(AttachedTemplateFileUnavailableError):
            await promotion_container.flow_template_asset_service().create_from_existing_attached_file(
                flow_id=flow.id,
                file_id=second_file.id,
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_changed_template_contract_rolls_back_promoted_asset(
    db_container,
) -> None:
    async with db_container() as setup_container:
        user, _space, flow, file = await _create_flow_and_file(
            setup_container,
            placeholder="customer.name",
        )

    async with db_container(user=user) as container:
        with pytest.raises(BadRequestException) as exc_info:
            async with container.session().begin_nested():
                await materialize_template_attachment(
                    intent=TemplateAttachmentIntent(
                        file_id=file.id,
                        terminal_plan_step_ref="step_b",
                    ),
                    changeset=_template_changeset(),
                    flow_id=flow.id,
                    template_asset_service=container.flow_template_asset_service(),
                )

        assert exc_info.value.code == "architecture_materialization_failed"
        asset_count = await container.session().scalar(
            sa.select(sa.func.count(FlowTemplateAssets.id)).where(
                FlowTemplateAssets.flow_id == flow.id,
                FlowTemplateAssets.file_id == file.id,
            )
        )
        assert asset_count == 0
        assert (
            await container.session().scalar(
                sa.select(Files.id).where(Files.id == file.id)
            )
            == file.id
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_materialized_template_attachment_publishes_with_pinned_identity(
    db_container,
) -> None:
    async with db_container() as setup_container:
        user, _space, flow, file = await _create_flow_and_file(
            setup_container,
            placeholder="case_id",
        )

    async with db_container(user=user) as container:
        changeset = FlowDraftChangeSet(
            flow_name=flow.name,
            flow_description="",
            compiled_steps=[
                FlowDraftCompiledStep(
                    plan_step_ref="step_a",
                    change_kind=FlowDraftStepChangeKind.ADDED,
                    step_order=1,
                    user_description="Fill template",
                    input_source="flow_input",
                    input_type="text",
                    output_mode="template_fill",
                    output_type="docx",
                    output_config={"bindings": {"case_id": "{{ flow_input.case_id }}"}},
                )
            ],
        )
        materialized = await materialize_template_attachment(
            intent=TemplateAttachmentIntent(
                file_id=file.id,
                terminal_plan_step_ref="step_a",
            ),
            changeset=changeset,
            flow_id=flow.id,
            template_asset_service=container.flow_template_asset_service(),
        )
        assistant, _ = await container.flow_service().create_flow_assistant(
            flow_id=flow.id,
            name="template-fill",
        )
        terminal = materialized.changeset.compiled_steps[0]
        updated = await container.flow_service().update_flow(
            flow_id=flow.id,
            metadata_json=materialized.changeset.metadata_json,
            steps=[
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=terminal.step_order,
                    user_description=terminal.user_description,
                    input_source=terminal.input_source,
                    input_type=terminal.input_type,
                    output_mode=terminal.output_mode,
                    output_type=terminal.output_type,
                    output_config=terminal.output_config,
                )
            ],
        )
        await container.flow_service().replace_resource_bindings(
            flow_id=flow.id,
            bindings=(materialized.binding,),
            source=FlowResourceBindingSource.AI_BUILDER,
        )

        published = await container.flow_service().publish_flow(flow_id=updated.id)

        assert published.published_version == 1
        definition = await container.session().scalar(
            sa.select(FlowVersions.definition_json).where(
                FlowVersions.flow_id == flow.id,
                FlowVersions.tenant_id == user.tenant_id,
                FlowVersions.version == 1,
            )
        )
        assert isinstance(definition, dict)
        output_config = definition["steps"][0]["output_config"]
        assert output_config["template_asset_id"] == str(materialized.binding.local_id)
        assert output_config["template_checksum"] == file.checksum
        assert output_config["placeholders"] == ["case_id"]
        assert output_config["bindings"] == {"case_id": "{{ flow_input.case_id }}"}
