from __future__ import annotations

from uuid import uuid4

import pytest

from intric.ai_models.model_enums import ModelFamily, ModelHostingLocation, ModelOrg, ModelStability
from intric.database.tables.ai_models_table import TranscriptionModels
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.spaces_table import SpacesTranscriptionModels
from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_materializer import compile_changeset, execute_changeset
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.flow import FlowStep
from intric.prompts.api.prompt_models import PromptCreate


async def _create_default_transcription_model(session, *, tenant_id, space_id):
    provider = ModelProviders(
        tenant_id=tenant_id,
        name="OpenAI Transcription",
        provider_type="openai",
        credentials={"api_key": "test-key"},
        config={},
        is_active=True,
    )
    session.add(provider)
    await session.flush()

    model = TranscriptionModels(
        tenant_id=tenant_id,
        provider_id=provider.id,
        name="whisper-1",
        model_name="whisper-1",
        family=ModelFamily.OPEN_AI.value,
        hosting=ModelHostingLocation.USA.value,
        stability=ModelStability.STABLE.value,
        org=ModelOrg.OPENAI.value,
        base_url="https://api.openai.com/v1",
        is_enabled=True,
        is_default=True,
    )
    session.add(model)
    await session.flush()

    session.add(
        SpacesTranscriptionModels(
            space_id=space_id,
            transcription_model_id=model.id,
        )
    )
    await session.flush()
    return model


def _make_flow_step(
    *,
    assistant_id,
    step_order: int,
    user_description: str,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    input_bindings: dict | None = None,
    input_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=None,
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id,
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy="inherit",
        input_bindings=input_bindings,
        input_contract=None,
        output_contract=None,
        input_config=input_config,
        output_config=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_execute_changeset_clears_stale_runtime_input_after_transcription_first_edit(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "AI Builder edit runtime input",
            [model.id],
            user_id=admin_user.id,
        )
        flow_service = container.flow_service()
        transcription_model = await _create_default_transcription_model(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
        )

        flow = await flow_service.create_flow(
            space_id=space.id,
            name="IBIC dokumentflöde",
            description="Tar emot dokument och analyserar dem.",
            steps=[],
        )
        analysis_assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id,
            name="analysis",
        )

        flow = await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _make_flow_step(
                    assistant_id=analysis_assistant.id,
                    step_order=1,
                    user_description="IBIC-extraktion",
                    input_source="flow_input",
                    input_type="document",
                    input_config={
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "input_format": "document",
                            "description": "Ladda upp dokument som detta steg ska analysera.",
                        }
                    },
                ),
            ],
        )

        edit_draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="before", anchor_ref="existing_step_1"),
                    add_payload=AddStepPayload(
                        name="Transkribera ljudfil",
                        assistant_spec=AssistantSpec(
                            instructions="Transkribera ljudfilen ordagrant till svensk text.",
                        ),
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        assistant_spec=AssistantSpec(instructions="Analysera transkriberingen."),
                    ),
                ),
            ],
        )

        compiled = compile_edit_draft(
            edit_draft,
            list(flow.steps),
            base_flow_revision=flow.draft_revision,
            flow_name=flow.name,
            flow_description=flow.description,
        )
        changeset = compile_changeset(
            compiled.compiled_spec,
            current_flow=flow,
            default_transcription_model_id=transcription_model.id,
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=flow_service,
            space_id=space.id,
            flow_id=flow.id,
            expected_revision=flow.draft_revision,
        )

        updated = await flow_service.get_flow(flow.id)
        assert len(updated.steps) == 2
        assert updated.steps[0].user_description == "Transkribera ljudfil"
        assert updated.steps[0].input_source == "flow_input"
        assert updated.steps[0].input_type == "audio"
        assert updated.steps[0].output_mode == "transcribe_only"
        assert updated.steps[0].output_type == "text"
        assert updated.steps[0].input_config == {
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "description": "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
            }
        }

        assert updated.steps[1].user_description == "IBIC-extraktion"
        assert updated.steps[1].input_source == "previous_step"
        assert updated.steps[1].input_type == "text"
        assert updated.steps[1].input_config is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_output_only_edit_updates_stale_flow_description_when_terminal_artifact_changes(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "AI Builder edit description",
            [model.id],
            user_id=admin_user.id,
        )
        flow_service = container.flow_service()

        original_description = (
            "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
            "svenskt beslutsunderlag i textformat."
        )

        flow = await flow_service.create_flow(
            space_id=space.id,
            name="Beslutsunderlag",
            description=original_description,
            steps=[],
        )
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id,
            name="summary",
        )
        await flow_service.update_flow_assistant(
            flow_id=flow.id,
            assistant_id=assistant.id,
            prompt=PromptCreate(text="Skriv ett kort beslutsunderlag i textformat."),
        )
        flow = await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _make_flow_step(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Skriv beslutsunderlag",
                    input_source="flow_input",
                    input_type="document",
                    output_type="text",
                ),
            ],
        )

        edit_draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        output_type=OutputType.DOCX,
                    ),
                ),
            ],
        )

        assistant_snapshots = await flow_service.get_flow_assistant_snapshots(flow)
        compiled = compile_edit_draft(
            edit_draft,
            list(flow.steps),
            base_flow_revision=flow.draft_revision,
            flow_name=flow.name,
            flow_description=flow.description,
            assistant_snapshots=assistant_snapshots,
        )
        changeset = compile_changeset(compiled.compiled_spec, current_flow=flow)

        await execute_changeset(
            changeset=changeset,
            flow_service=flow_service,
            space_id=space.id,
            flow_id=flow.id,
            expected_revision=flow.draft_revision,
        )

        updated = await flow_service.get_flow(flow.id)
        updated_snapshots = await flow_service.get_flow_assistant_snapshots(updated)
        assert updated.steps[0].output_type == "docx"
        assert updated.description == (
            "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
            "svenskt beslutsunderlag i DOCX-format."
        )
        assert updated_snapshots[updated.steps[0].assistant_id]["instructions"] == (
            "Skriv ett kort beslutsunderlag i textformat."
        )
