"""Tests for AI Builder materializer (compiler + executor)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_materializer import (
    compile_changeset,
    execute_changeset,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    AssistantToCreate,
    AssistantToDelete,
    AssistantToUpdate,
    FlowChangeSet,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepChangeKind,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    MaterializerProgressSnapshot,
)
from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from intric.main.exceptions import BadRequestException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(
    *,
    flow_name: str = "Test flow",
    flow_description: str = "A test flow",
    steps: list[StepSpec] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=flow_name,
        flow_description=flow_description,
        steps=steps or [],
    )


def _make_step_spec(
    *,
    plan_step_ref: str = "step_a",
    existing_step_ref: str | None = None,
    name: str = "Test step",
    instructions: str = "Do the thing.",
    model_ref: str | None = None,
    knowledge_refs: list[str] | None = None,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    mcp_policy: MCPPolicy = MCPPolicy.INHERIT,
    input_bindings: dict[str, Any] | None = None,
    input_contract: dict[str, Any] | None = None,
    output_contract: dict[str, Any] | None = None,
    input_config: dict[str, Any] | None = None,
    output_config: dict[str, Any] | None = None,
    review_policy: FlowStepReviewPolicy | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(
            instructions=instructions,
            model_ref=model_ref,
            knowledge_refs=knowledge_refs or [],
        ),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy=mcp_policy,
        input_bindings=input_bindings,
        input_contract=input_contract,
        output_contract=output_contract,
        input_config=input_config,
        output_config=output_config,
        review_policy=review_policy,
    )


def _make_flow(
    *,
    name: str = "Existing flow",
    description: str | None = "An existing flow",
    steps: list[FlowStep] | None = None,
    published_version: int | None = None,
    draft_revision: int = 0,
    metadata_json: dict | None = None,
    flow_id: UUID | None = None,
    space_id: UUID | None = None,
) -> Flow:
    return Flow(
        id=flow_id or uuid4(),
        tenant_id=uuid4(),
        space_id=space_id or uuid4(),
        name=name,
        description=description,
        steps=steps or [],
        published_version=published_version,
        draft_revision=draft_revision,
        metadata_json=metadata_json,
    )


def _make_flow_step(
    *,
    step_order: int = 1,
    user_description: str = "Existing step",
    assistant_id: UUID | None = None,
    step_id: UUID | None = None,
    flow_id: UUID | None = None,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    mcp_policy: str = "inherit",
    input_bindings: dict | None = None,
    input_contract: dict | None = None,
    output_contract: dict | None = None,
    input_config: dict | None = None,
    output_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=step_id or uuid4(),
        flow_id=flow_id or uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id or uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy=mcp_policy,
        input_bindings=input_bindings,
        input_contract=input_contract,
        output_contract=output_contract,
        input_config=input_config,
        output_config=output_config,
    )


# ---------------------------------------------------------------------------
# Compiler: create flow (no existing flow)
# ---------------------------------------------------------------------------


class TestCompileCreateFlow:
    """Tests for compiling a spec into a changeset when creating a new flow."""

    def test_empty_spec_creates_empty_changeset(self) -> None:
        spec = _make_spec(steps=[])
        changeset = compile_changeset(spec, current_flow=None)
        assert changeset.flow_name == "Test flow"
        assert changeset.flow_description == "A test flow"
        assert changeset.assistants_to_create == []
        assert changeset.assistants_to_update == []
        assert changeset.assistants_to_delete == []
        assert changeset.compiled_steps == []

    def test_single_step_creates_one_assistant(self) -> None:
        spec = _make_spec(
            steps=[
                _make_step_spec(plan_step_ref="step_a", name="Extrahera fakta"),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        assert len(changeset.assistants_to_create) == 1
        assert changeset.assistants_to_create[0].plan_step_ref == "step_a"
        assert (
            changeset.assistants_to_create[0].assistant_spec.instructions
            == "Do the thing."
        )
        assert len(changeset.compiled_steps) == 1
        assert changeset.compiled_steps[0].step_order == 1
        assert changeset.compiled_steps[0].user_description == "Extrahera fakta"
        assert changeset.compiled_steps[0].change_kind == StepChangeKind.ADDED

    def test_single_step_preserves_review_policy(self) -> None:
        review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Granska transkribering",
                    review_policy=review_policy,
                ),
            ],
        )

        changeset = compile_changeset(spec, current_flow=None)

        assert changeset.compiled_steps[0].review_policy == review_policy

    def test_three_step_creates_correct_order(self) -> None:
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Step A",
                    input_source=InputSource.FLOW_INPUT,
                ),
                _make_step_spec(
                    plan_step_ref="step_b",
                    name="Step B",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
                _make_step_spec(
                    plan_step_ref="step_c",
                    name="Step C",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        assert len(changeset.assistants_to_create) == 3
        assert len(changeset.compiled_steps) == 3
        assert changeset.compiled_steps[0].step_order == 1
        assert changeset.compiled_steps[1].step_order == 2
        assert changeset.compiled_steps[2].step_order == 3
        assert all(
            s.change_kind == StepChangeKind.ADDED for s in changeset.compiled_steps
        )

    def test_assistant_id_is_none_for_new_steps(self) -> None:
        spec = _make_spec(
            steps=[_make_step_spec(plan_step_ref="step_a")],
        )
        changeset = compile_changeset(spec, current_flow=None)
        assert changeset.compiled_steps[0].assistant_id is None

    def test_step_fields_propagate_correctly(self) -> None:
        bindings = {"question": "{{ Ärendenummer }}"}  # Form field var — not rewritten
        contract = {"type": "object", "properties": {"x": {"type": "string"}}}
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="JSON Step",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.JSON,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.JSON,
                    mcp_policy=MCPPolicy.RESTRICTED,
                    input_bindings=bindings,
                    input_contract=contract,
                    output_contract=contract,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        step = changeset.compiled_steps[0]
        assert step.input_source == "flow_input"
        assert step.input_type == "json"
        assert step.output_mode == "pass_through"
        assert step.output_type == "json"
        assert step.mcp_policy == "restricted"
        assert step.input_bindings == bindings
        assert step.input_contract == contract
        assert step.output_contract == contract

    def test_document_flow_input_defaults_runtime_upload_config(self) -> None:
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Extrahera dokumentpaket",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.DOCUMENT,
                ),
            ],
        )

        changeset = compile_changeset(spec, current_flow=None)

        step = changeset.compiled_steps[0]
        assert step.input_config == {
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "description": "Ladda upp dokument som detta steg ska analysera.",
            }
        }

    def test_explicit_runtime_upload_config_is_preserved(self) -> None:
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Bearbeta ljud",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                    input_config={
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "input_format": "audio",
                            "description": "Ladda upp mötesinspelningen.",
                        }
                    },
                ),
            ],
        )

        changeset = compile_changeset(spec, current_flow=None)

        assert changeset.compiled_steps[0].input_config == {
            "runtime_input": {
                "enabled": True,
                "required": True,
                "input_format": "audio",
                "description": "Ladda upp mötesinspelningen.",
            }
        }

    def test_form_fields_become_metadata_json(self) -> None:
        from intric.flows.ai_builder.ai_builder_models import FormFieldSpec

        spec = FlowDraftSpecCore(
            flow_name="Form flow",
            flow_description="",
            steps=[
                _make_step_spec(plan_step_ref="step_a"),
            ],
            form_fields=[
                FormFieldSpec(
                    name="Ärendenummer",
                    type="text",
                    label="Ärendenummer",
                    required=True,
                ),
                FormFieldSpec(
                    name="Prioritet",
                    type="select",
                    label="Prioritet",
                    options=["hög", "medel", "låg"],
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        assert changeset.metadata_json is not None
        form_schema = changeset.metadata_json.get("form_schema")
        assert form_schema is not None
        fields = form_schema["fields"]
        assert len(fields) == 2
        assert fields[0]["name"] == "Ärendenummer"
        assert fields[0]["required"] is True
        assert fields[1]["name"] == "Prioritet"
        assert fields[1]["options"] == ["hög", "medel", "låg"]

    def test_audio_flow_input_defaults_transcription_metadata(self) -> None:
        model_id = uuid4()
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Transkribera ljud",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        changeset = compile_changeset(
            spec,
            current_flow=None,
            default_transcription_model_id=model_id,
        )

        assert changeset.metadata_json is not None
        wizard = changeset.metadata_json["wizard"]
        assert wizard == {
            "transcription_enabled": True,
            "transcription_model": {"id": str(model_id)},
            "transcription_language": "auto",
        }
        # Provenance is also stamped
        assert (
            changeset.metadata_json["ai_builder"]["description"]["mode"]
            == "builder_managed"
        )

    def test_audio_flow_input_preserves_existing_transcription_metadata(self) -> None:
        existing_model_id = uuid4()
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Transkribera ljud",
                    existing_step_ref="existing_step_1",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                    output_type=OutputType.TEXT,
                ),
            ],
        )
        current_flow = _make_flow(
            metadata_json={
                "wizard": {
                    "transcription_enabled": False,
                    "transcription_model": {"id": str(existing_model_id)},
                    "transcription_language": "tr",
                }
            },
            steps=[
                _make_flow_step(
                    step_order=1,
                    input_source="flow_input",
                    input_type="audio",
                    output_mode="transcribe_only",
                    output_type="text",
                )
            ],
        )

        changeset = compile_changeset(spec, current_flow=current_flow)

        assert changeset.metadata_json is not None
        wizard = changeset.metadata_json["wizard"]
        assert wizard == {
            "transcription_enabled": True,
            "transcription_model": {"id": str(existing_model_id)},
            "transcription_language": "tr",
        }


# ---------------------------------------------------------------------------
# Compiler: edit flow (existing flow with steps)
# ---------------------------------------------------------------------------


class TestCompileEditFlow:
    """Tests for compiling a spec against an existing flow."""

    def test_modify_existing_step(self) -> None:
        """existing_step_ref matches → MODIFIED, reuse assistant_id."""
        existing_step = _make_flow_step(
            step_order=1,
            user_description="Old name",
        )
        flow = _make_flow(steps=[existing_step])
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref=f"existing_step_{existing_step.step_order}",
                    name="New name",
                    instructions="Updated instructions",
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        assert len(changeset.assistants_to_update) == 1
        assert (
            changeset.assistants_to_update[0].existing_assistant_id
            == existing_step.assistant_id
        )
        assert (
            changeset.assistants_to_update[0].assistant_spec.instructions
            == "Updated instructions"
        )
        assert len(changeset.compiled_steps) == 1
        assert changeset.compiled_steps[0].change_kind == StepChangeKind.MODIFIED
        assert changeset.compiled_steps[0].assistant_id == existing_step.assistant_id
        assert changeset.compiled_steps[0].user_description == "New name"

    def test_add_new_step_to_existing_flow(self) -> None:
        """New step (no existing_step_ref) added to existing flow."""
        existing_step = _make_flow_step(step_order=1, user_description="Existing")
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Existing",
                ),
                _make_step_spec(
                    plan_step_ref="step_b",
                    name="Brand new",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        assert len(changeset.assistants_to_create) == 1
        assert changeset.assistants_to_create[0].plan_step_ref == "step_b"
        assert len(changeset.assistants_to_update) == 1
        new_step = [
            s for s in changeset.compiled_steps if s.change_kind == StepChangeKind.ADDED
        ]
        assert len(new_step) == 1
        assert new_step[0].plan_step_ref == "step_b"
        assert new_step[0].assistant_id is None

    def test_remove_existing_step(self) -> None:
        """Steps in existing flow not referenced in spec → REMOVED."""
        step1 = _make_flow_step(step_order=1, user_description="Keep")
        step2 = _make_flow_step(step_order=2, user_description="Remove")
        flow = _make_flow(steps=[step1, step2])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Keep",
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        assert len(changeset.assistants_to_delete) == 1
        assert changeset.assistants_to_delete[0].step_id == step2.id
        assert changeset.assistants_to_delete[0].assistant_id == step2.assistant_id

    def test_mixed_add_modify_remove(self) -> None:
        """Complex scenario: modify one, add one, remove one."""
        step1 = _make_flow_step(step_order=1, user_description="Modify me")
        step2 = _make_flow_step(step_order=2, user_description="Delete me")
        flow = _make_flow(steps=[step1, step2])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Modified",
                    instructions="New prompt",
                ),
                _make_step_spec(
                    plan_step_ref="step_b",
                    name="Brand new step",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        assert len(changeset.assistants_to_create) == 1
        assert len(changeset.assistants_to_update) == 1
        assert len(changeset.assistants_to_delete) == 1
        assert changeset.assistants_to_delete[0].assistant_id == step2.assistant_id
        # Step orders should be sequential
        assert changeset.compiled_steps[0].step_order == 1
        assert changeset.compiled_steps[1].step_order == 2

    def test_preserve_unspecified_fields_from_existing_step(self) -> None:
        """Fields not in the spec (input_config, output_config) are preserved."""
        existing_config = {"custom_hint": "preserve-me"}
        existing_output_config = {"webhook_url": "https://example.com"}
        existing_step = _make_flow_step(
            step_order=1,
            input_config=existing_config,
            output_config=existing_output_config,
        )
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Updated",
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        step = changeset.compiled_steps[0]
        assert step.input_config == existing_config
        assert step.output_config == existing_output_config

    def test_runtime_input_is_removed_when_step_no_longer_uses_flow_input_uploads(
        self,
    ) -> None:
        """Editing a file-upload step into a previous-step text step must drop stale runtime_input."""
        existing_step = _make_flow_step(
            step_order=1,
            user_description="Analysera dokument",
            input_source="flow_input",
            input_type="document",
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "input_format": "document",
                    "description": "Ladda upp dokument som detta steg ska analysera.",
                },
                "legacy_marker": "keep-me",
            },
        )
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Analysera transkribering",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                ),
            ],
        )

        changeset = compile_changeset(spec, current_flow=flow)

        assert changeset.compiled_steps[0].input_config == {
            "legacy_marker": "keep-me",
        }

    def test_invalid_existing_step_ref_raises_bad_request(self) -> None:
        """If existing_step_ref doesn't match any step → typed bad request with valid refs."""
        step1 = _make_flow_step(step_order=1, user_description="Step 1")
        flow = _make_flow(steps=[step1])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_99",  # doesn't exist
                    name="Ghost ref",
                ),
            ],
        )
        with pytest.raises(BadRequestException, match="existing_step_99") as exc_info:
            compile_changeset(spec, current_flow=flow)
        assert exc_info.value.code == "invalid_existing_step_ref"

    def test_reorder_existing_steps(self) -> None:
        """Reordering steps should update step_order correctly."""
        step1 = _make_flow_step(step_order=1, user_description="First")
        step2 = _make_flow_step(step_order=2, user_description="Second")
        flow = _make_flow(steps=[step1, step2])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_b",
                    existing_step_ref="existing_step_2",
                    name="Second (now first)",
                    input_source=InputSource.FLOW_INPUT,
                ),
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="First (now second)",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        assert changeset.compiled_steps[0].step_order == 1
        assert changeset.compiled_steps[0].assistant_id == step2.assistant_id
        assert changeset.compiled_steps[1].step_order == 2
        assert changeset.compiled_steps[1].assistant_id == step1.assistant_id

    def test_output_mode_change_clears_stale_output_config(self) -> None:
        """When output_mode changes, stale output_config from existing step must be cleared."""
        existing_step = _make_flow_step(
            step_order=1,
            output_mode="template_fill",
            output_config={"template_asset_id": "old-template-uuid"},
        )
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Updated",
                    output_mode=OutputMode.PASS_THROUGH,  # changed from template_fill
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        step = changeset.compiled_steps[0]
        # output_config should be cleared because output_mode changed
        assert step.output_config is None

    def test_same_output_mode_preserves_output_config(self) -> None:
        """When output_mode is unchanged, existing output_config is preserved."""
        existing_step = _make_flow_step(
            step_order=1,
            output_mode="template_fill",
            output_type="docx",
            output_config={"template_asset_id": "keep-me"},
        )
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Updated",
                    output_mode=OutputMode.TEMPLATE_FILL,  # same mode
                    output_type=OutputType.DOCX,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        step = changeset.compiled_steps[0]
        assert step.output_config == {"template_asset_id": "keep-me"}

    def test_output_mode_change_with_new_output_config_uses_new(self) -> None:
        """When output_mode changes AND spec provides new output_config, use the new one."""
        existing_step = _make_flow_step(
            step_order=1,
            output_mode="template_fill",
            output_config={"template_asset_id": "old-template"},
        )
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="Updated",
                    output_mode=OutputMode.PASS_THROUGH,
                    output_config={"new_key": "new_value"},
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        step = changeset.compiled_steps[0]
        assert step.output_config == {"new_key": "new_value"}

    def test_output_type_change_strips_stale_citation_mode(self) -> None:
        existing_step = _make_flow_step(
            step_order=1,
            output_type="text",
            output_mode="pass_through",
            output_config={"citation_mode": "inline_inref_sidecar"},
        )
        flow = _make_flow(steps=[existing_step])

        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    name="PDF report",
                    output_type=OutputType.PDF,
                ),
            ],
        )

        changeset = compile_changeset(spec, current_flow=flow)

        assert changeset.compiled_steps[0].output_type == OutputType.PDF
        assert changeset.compiled_steps[0].output_config is None


# ---------------------------------------------------------------------------
# Compiler: metadata and form fields
# ---------------------------------------------------------------------------


class TestCompileMetadata:
    def test_form_fields_none_still_has_provenance(self) -> None:
        """Even without form fields, provenance is stamped."""
        spec = _make_spec(steps=[_make_step_spec(plan_step_ref="step_a")])
        changeset = compile_changeset(spec, current_flow=None)
        assert changeset.metadata_json is not None
        assert "ai_builder" in changeset.metadata_json
        assert "form_schema" not in changeset.metadata_json

    def test_preserves_existing_metadata_when_no_form_fields(self) -> None:
        """When editing, preserve existing metadata if spec has no form_fields."""
        flow = _make_flow(metadata_json={"custom_key": "value"})
        spec = _make_spec(steps=[_make_step_spec(plan_step_ref="step_a")])
        changeset = compile_changeset(spec, current_flow=flow)
        assert changeset.metadata_json is not None
        assert changeset.metadata_json.get("custom_key") == "value"

    def test_form_fields_override_existing_form_schema(self) -> None:
        """When spec has form_fields, they replace existing form_schema."""
        from intric.flows.ai_builder.ai_builder_models import FormFieldSpec

        flow = _make_flow(
            metadata_json={
                "custom_key": "preserve",
                "form_schema": {"fields": [{"name": "old", "type": "text"}]},
            }
        )
        spec = FlowDraftSpecCore(
            flow_name="Test",
            flow_description="",
            steps=[_make_step_spec(plan_step_ref="step_a")],
            form_fields=[
                FormFieldSpec(name="New field", type="text", label="New field"),
            ],
        )
        changeset = compile_changeset(spec, current_flow=flow)
        assert changeset.metadata_json is not None
        # Custom key preserved
        assert changeset.metadata_json.get("custom_key") == "preserve"
        # Form schema replaced
        fields = changeset.metadata_json["form_schema"]["fields"]
        assert len(fields) == 1
        assert fields[0]["name"] == "New field"


# ---------------------------------------------------------------------------
# Compiler: description provenance
# ---------------------------------------------------------------------------


class TestDescriptionProvenance:
    def test_create_mode_stamps_builder_managed_provenance(self) -> None:
        """New flow gets builder_managed provenance with signature and hash."""
        spec = _make_spec(
            flow_description="Tar emot dokument och analyserar dem.",
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.PDF,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        assert changeset.metadata_json is not None
        ai_builder = changeset.metadata_json.get("ai_builder", {})
        desc_prov = ai_builder.get("description", {})
        assert desc_prov["mode"] == "builder_managed"
        assert desc_prov["semantic_signature"]["entry_input_type"] == "document"
        assert desc_prov["semantic_signature"]["terminal_output_type"] == "pdf"
        assert desc_prov["last_generated_hash"] is not None

    def test_description_override_manual_stamps_manual_provenance(self) -> None:
        """When description_override_manual=True is passed, stamp manual provenance."""
        spec = _make_spec(
            flow_description="User wrote this.",
            steps=[_make_step_spec(plan_step_ref="step_a")],
        )
        changeset = compile_changeset(
            spec,
            current_flow=None,
            description_override_manual=True,
        )
        assert changeset.metadata_json is not None
        ai_builder = changeset.metadata_json.get("ai_builder", {})
        desc_prov = ai_builder.get("description", {})
        assert desc_prov["mode"] == "manual"

    def test_edit_mode_preserves_existing_ai_builder_metadata(self) -> None:
        """Provenance update should preserve other ai_builder metadata keys."""
        flow = _make_flow(
            metadata_json={
                "ai_builder": {"other_key": "preserve_me"},
                "custom": "data",
            }
        )
        spec = _make_spec(
            flow_description="Updated description.",
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                )
            ],
        )
        flow.steps = [_make_flow_step(step_order=1)]
        changeset = compile_changeset(spec, current_flow=flow)
        assert changeset.metadata_json is not None
        assert changeset.metadata_json.get("custom") == "data"
        ai_builder = changeset.metadata_json["ai_builder"]
        assert ai_builder.get("other_key") == "preserve_me"
        assert "description" in ai_builder

    def test_compile_changeset_stamps_ai_builder_origin_metadata(self) -> None:
        spec = _make_spec(steps=[_make_step_spec(plan_step_ref="step_a")])

        changeset = compile_changeset(
            spec,
            current_flow=None,
            ai_builder_origin={
                "builder_session_id": str(uuid4()),
                "builder_plan_id": str(uuid4()),
                "builder_spec_hash": spec.spec_hash(),
                "applied_at": "2026-03-31T12:00:00Z",
            },
        )

        assert changeset.metadata_json is not None
        ai_builder = changeset.metadata_json["ai_builder"]
        assert ai_builder["origin"]["builder_spec_hash"] == spec.spec_hash()
        assert ai_builder["origin"]["applied_at"] == "2026-03-31T12:00:00Z"

    def test_edit_mode_tolerates_existing_http_get_input_source(self) -> None:
        flow = _make_flow(
            description="Fetches a remote payload and summarizes it.",
            steps=[
                _make_flow_step(
                    step_order=1,
                    input_source="http_get",
                    output_mode="pass_through",
                    output_type="text",
                )
            ],
        )
        spec = _make_spec(
            flow_description=flow.description or "",
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    input_source=InputSource.FLOW_INPUT,
                )
            ],
        )

        changeset = compile_changeset(spec, current_flow=flow)

        assert changeset.flow_description == flow.description

    def test_edit_mode_tolerates_existing_http_post_output_mode(self) -> None:
        flow = _make_flow(
            description="Posts the result to another system.",
            steps=[
                _make_flow_step(
                    step_order=1,
                    input_source="flow_input",
                    output_mode="http_post",
                    output_type="json",
                )
            ],
        )
        spec = _make_spec(
            flow_description=flow.description or "",
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_1",
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.JSON,
                )
            ],
        )

        changeset = compile_changeset(spec, current_flow=flow)

        assert changeset.flow_description == flow.description


# ---------------------------------------------------------------------------
# Compiler: variable binding rewriting (plan_step_ref → step order refs)
# ---------------------------------------------------------------------------


class TestCompileVariableBindings:
    def test_plan_step_ref_rewritten_in_bindings(self) -> None:
        """plan_step_ref references in bindings are rewritten to step_N references."""
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Extrahera",
                    input_source=InputSource.FLOW_INPUT,
                ),
                _make_step_spec(
                    plan_step_ref="step_b",
                    name="Sammanfatta",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_bindings={"question": "Data: {{ step_a.output.text }}"},
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        step_b = changeset.compiled_steps[1]
        # step_a is step_order 1, so {{ step_a.output.text }} → {{ step_1.output.text }}
        assert step_b.input_bindings is not None
        assert "{{ step_1.output.text }}" in step_b.input_bindings["question"]

    def test_plan_step_ref_rewritten_in_instructions(self) -> None:
        """plan_step_ref in assistant instructions are also rewritten."""
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="extract",
                    name="Extrahera",
                    input_source=InputSource.FLOW_INPUT,
                ),
                _make_step_spec(
                    plan_step_ref="summarize",
                    name="Sammanfatta",
                    instructions="Baserat på {{ extract.output.text }} och {{ extract.output.summary }}",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        # extract → step_order 1
        create_for_summarize = [
            a for a in changeset.assistants_to_create if a.plan_step_ref == "summarize"
        ]
        assert len(create_for_summarize) == 1
        rewritten = create_for_summarize[0].assistant_spec.instructions
        assert "{{ step_1.output.text }}" in rewritten
        assert "{{ step_1.output.summary }}" in rewritten

    def test_no_rewrite_for_system_variables(self) -> None:
        """System variables like {{ föregående_steg }} should not be rewritten."""
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    input_bindings={
                        "question": "{{ föregående_steg }} and {{ datum }}"
                    },
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        bindings = changeset.compiled_steps[0].input_bindings
        assert bindings is not None
        assert "{{ föregående_steg }}" in bindings["question"]
        assert "{{ datum }}" in bindings["question"]

    def test_no_rewrite_for_form_field_variables(self) -> None:
        """Form field variables like {{ Ärendenummer }} should not be rewritten."""
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    input_bindings={"question": "Ärende: {{ Ärendenummer }}"},
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        bindings = changeset.compiled_steps[0].input_bindings
        assert bindings is not None
        assert "{{ Ärendenummer }}" in bindings["question"]

    def test_plan_step_ref_rewritten_in_template_fill_output_bindings(self) -> None:
        spec = _make_spec(
            steps=[
                _make_step_spec(
                    plan_step_ref="step_a",
                    name="Extrahera",
                    input_source=InputSource.FLOW_INPUT,
                ),
                _make_step_spec(
                    plan_step_ref="step_b",
                    name="Fyll mall",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_mode=OutputMode.TEMPLATE_FILL,
                    output_type=OutputType.DOCX,
                    output_config={
                        "bindings": {
                            "SUMMARY": "{{ step_a.output.text }}",
                        }
                    },
                ),
            ],
        )
        changeset = compile_changeset(spec, current_flow=None)
        assert changeset.compiled_steps[1].output_config == {
            "bindings": {
                "SUMMARY": "{{ step_1.output.text }}",
            }
        }


# ---------------------------------------------------------------------------
# Executor: create flow
# ---------------------------------------------------------------------------


class TestExecuteCreateFlow:
    """Tests for the executor that creates assistants and calls FlowService."""

    @pytest.mark.asyncio
    async def test_create_flow_with_single_step(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        created_flow = _make_flow(
            flow_id=flow_id,
            space_id=space_id,
            name="Created flow",
        )
        mock_flow_service.create_flow.return_value = created_flow

        mock_assistant = MagicMock()
        mock_assistant.id = assistant_id
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])

        changeset = FlowChangeSet(
            flow_name="Created flow",
            flow_description="Desc",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Do stuff"),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.ADDED,
                    user_description="Step A",
                ),
            ],
        )

        result = await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=None,  # create mode
        )

        # Create mode: creates empty flow, then updates with steps
        mock_flow_service.create_flow.assert_called_once()
        create_kwargs = mock_flow_service.create_flow.call_args.kwargs
        assert create_kwargs["name"] == "Created flow"
        assert create_kwargs["space_id"] == space_id
        assert create_kwargs["steps"] == []  # Empty initially

        # Then updates with real steps
        mock_flow_service.update_flow.assert_called_once()
        update_kwargs = mock_flow_service.update_flow.call_args.kwargs
        assert len(update_kwargs["steps"]) == 1
        assert update_kwargs["steps"][0].assistant_id == assistant_id
        assert result.flow_id == flow_id

    @pytest.mark.asyncio
    async def test_create_flow_preserves_step_review_policy(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()
        review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT)

        mock_flow_service = AsyncMock()
        mock_flow_service.create_flow.return_value = _make_flow(
            flow_id=flow_id,
            space_id=space_id,
            name="Created flow",
        )

        mock_assistant = MagicMock()
        mock_assistant.id = assistant_id
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])

        changeset = FlowChangeSet(
            flow_name="Created flow",
            flow_description="Desc",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Transcribe audio"),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.ADDED,
                    user_description="Transkribera",
                    review_policy=review_policy,
                ),
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=None,
        )

        update_kwargs = mock_flow_service.update_flow.call_args.kwargs
        assert update_kwargs["steps"][0].review_policy == review_policy

    @pytest.mark.asyncio
    async def test_create_flow_with_multiple_steps(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_ids = [uuid4(), uuid4(), uuid4()]

        mock_flow_service = AsyncMock()
        created_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.create_flow.return_value = created_flow

        call_count = 0

        async def mock_create_assistant(**kwargs):
            nonlocal call_count
            mock = MagicMock()
            mock.id = assistant_ids[call_count]
            call_count += 1
            return mock, []

        mock_flow_service.create_flow_assistant.side_effect = mock_create_assistant
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        changeset = FlowChangeSet(
            flow_name="Multi",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref=f"step_{c}",
                    assistant_spec=AssistantSpec(instructions=f"Step {c}"),
                )
                for c in "abc"
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref=f"step_{c}",
                    step_order=i + 1,
                    change_kind=StepChangeKind.ADDED,
                    user_description=f"Step {c.upper()}",
                )
                for i, c in enumerate("abc")
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=None,
        )

        assert mock_flow_service.create_flow_assistant.call_count == 3
        # Steps are in the update_flow call, not create_flow
        update_kwargs = mock_flow_service.update_flow.call_args.kwargs
        assert len(update_kwargs["steps"]) == 3
        # Verify assistant IDs were remapped
        for i, step in enumerate(update_kwargs["steps"]):
            assert step.assistant_id == assistant_ids[i]

    @pytest.mark.asyncio
    async def test_execute_changeset_reports_bounded_progress_snapshots(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_ids = [uuid4(), uuid4()]

        mock_flow_service = AsyncMock()
        created_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.create_flow.return_value = created_flow

        create_index = 0

        async def mock_create_assistant(**kwargs):
            nonlocal create_index
            mock = MagicMock()
            mock.id = assistant_ids[create_index]
            create_index += 1
            return mock, []

        mock_flow_service.create_flow_assistant.side_effect = mock_create_assistant
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        changeset = FlowChangeSet(
            flow_name="Progress",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref=f"step_{c}",
                    assistant_spec=AssistantSpec(instructions=f"Step {c}"),
                )
                for c in "ab"
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref=f"step_{c}",
                    step_order=i + 1,
                    change_kind=StepChangeKind.ADDED,
                    user_description=f"Step {c.upper()}",
                )
                for i, c in enumerate("ab")
            ],
        )
        snapshots: list[MaterializerProgressSnapshot] = []

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=None,
            progress_callback=snapshots.append,
        )

        assert [snapshot.stage for snapshot in snapshots] == [
            "flow_created",
            "assistants_created",
            "assistants_configured",
            "assistants_created",
            "assistants_configured",
            "flow_updated",
        ]
        assert snapshots[-1] == MaterializerProgressSnapshot(
            stage="flow_updated",
            assistants_created=2,
            assistants_configured=2,
            assistants_updated=0,
            assistants_deleted=0,
            flow_created=True,
            flow_updated=True,
        )

    @pytest.mark.asyncio
    async def test_execute_changeset_keeps_last_progress_before_update_failure(
        self,
    ) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        created_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.create_flow.return_value = created_flow
        mock_assistant = MagicMock()
        mock_assistant.id = assistant_id
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow.side_effect = RuntimeError("update failed")

        changeset = FlowChangeSet(
            flow_name="Progress failure",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Step A"),
                )
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.ADDED,
                )
            ],
        )
        snapshots: list[MaterializerProgressSnapshot] = []

        with pytest.raises(RuntimeError, match="update failed"):
            await execute_changeset(
                changeset=changeset,
                flow_service=mock_flow_service,
                space_id=space_id,
                flow_id=None,
                progress_callback=snapshots.append,
            )

        assert snapshots[-1] == MaterializerProgressSnapshot(
            stage="assistants_configured",
            assistants_created=1,
            assistants_configured=1,
            assistants_updated=0,
            assistants_deleted=0,
            flow_created=True,
            flow_updated=False,
        )

    @pytest.mark.asyncio
    async def test_assistant_configured_with_prompt(self) -> None:
        """Executor should call update_flow_assistant with PromptCreate."""
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()
        model_id = uuid4()
        kb_id_1 = uuid4()
        kb_id_2 = uuid4()

        mock_flow_service = AsyncMock()
        created_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.create_flow.return_value = created_flow

        mock_assistant = MagicMock()
        mock_assistant.id = assistant_id
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(
                        instructions="Detailed prompt here",
                        model_ref=str(model_id),
                        knowledge_refs=[str(kb_id_1), str(kb_id_2)],
                    ),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.ADDED,
                ),
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=None,
        )

        mock_flow_service.update_flow_assistant.assert_called_once()
        update_kwargs = mock_flow_service.update_flow_assistant.call_args.kwargs
        assert update_kwargs["prompt"].text == "Detailed prompt here"
        assert update_kwargs["completion_model_id"] == model_id
        assert update_kwargs["groups"] == [kb_id_1, kb_id_2]
        assert update_kwargs["websites"] == []
        assert update_kwargs["integration_knowledge_ids"] == []
        assert update_kwargs["mcp_server_ids"] == []
        assert update_kwargs["mcp_tools"] == []

    @pytest.mark.asyncio
    async def test_assistant_configured_with_mcp_refs(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()
        mcp_server_id = uuid4()
        mcp_tool_id = uuid4()

        mock_flow_service = AsyncMock()
        created_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.create_flow.return_value = created_flow

        mock_assistant = MagicMock()
        mock_assistant.id = assistant_id
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(
                        instructions="Fetch from the case system",
                        mcp_server_refs=[str(mcp_server_id)],
                        mcp_tool_refs=[str(mcp_tool_id)],
                    ),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.ADDED,
                ),
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=None,
        )

        update_kwargs = mock_flow_service.update_flow_assistant.call_args.kwargs
        assert update_kwargs["mcp_server_ids"] == [mcp_server_id]
        assert update_kwargs["mcp_tools"] == [(mcp_tool_id, True)]
        assert update_kwargs["groups"] == []

    @pytest.mark.asyncio
    async def test_create_mode_cleans_up_exact_temp_flow_when_apply_fails(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        mock_flow_service.create_flow.return_value = _make_flow(
            flow_id=flow_id,
            space_id=space_id,
            name="Created flow",
        )
        created_assistant = MagicMock()
        created_assistant.id = assistant_id
        mock_flow_service.create_flow_assistant.return_value = (created_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (created_assistant, [])
        mock_flow_service.update_flow.side_effect = RuntimeError("apply failed")

        changeset = FlowChangeSet(
            flow_name="Created flow",
            flow_description="Desc",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Do stuff"),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.ADDED,
                    user_description="Step A",
                ),
            ],
        )

        with pytest.raises(RuntimeError, match="apply failed"):
            await execute_changeset(
                changeset=changeset,
                flow_service=mock_flow_service,
                space_id=space_id,
                flow_id=None,
            )

        mock_flow_service.delete_flow.assert_awaited_once_with(flow_id)


# ---------------------------------------------------------------------------
# Executor: edit flow
# ---------------------------------------------------------------------------


class TestExecuteEditFlow:
    @pytest.mark.asyncio
    async def test_update_existing_step(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        updated_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.update_flow.return_value = updated_flow
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        changeset = FlowChangeSet(
            flow_name="Updated",
            flow_description="Desc",
            assistants_to_update=[
                AssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=assistant_id,
                    assistant_spec=AssistantSpec(instructions="New prompt"),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                ),
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
        )

        mock_flow_service.update_flow.assert_called_once()
        mock_flow_service.update_flow_assistant.assert_called_once()
        update_kwargs = mock_flow_service.update_flow_assistant.call_args.kwargs
        assert update_kwargs["flow_id"] == flow_id
        assert update_kwargs["assistant_id"] == assistant_id

    @pytest.mark.asyncio
    async def test_delete_removed_assistants(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        deleted_assistant_id = uuid4()
        deleted_step_id = uuid4()

        mock_flow_service = AsyncMock()
        updated_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.update_flow.return_value = updated_flow

        changeset = FlowChangeSet(
            flow_name="Trimmed",
            flow_description="",
            assistants_to_delete=[
                AssistantToDelete(
                    step_id=deleted_step_id,
                    assistant_id=deleted_assistant_id,
                ),
            ],
            compiled_steps=[],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
        )

        mock_flow_service.delete_flow_assistant.assert_called_once_with(
            flow_id=flow_id,
            assistant_id=deleted_assistant_id,
        )

    @pytest.mark.asyncio
    async def test_mixed_create_update_delete(self) -> None:
        """Full scenario: create new, update existing, delete removed."""
        flow_id = uuid4()
        space_id = uuid4()
        existing_assistant_id = uuid4()
        deleted_assistant_id = uuid4()
        new_assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        updated_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.update_flow.return_value = updated_flow

        mock_new_assistant = MagicMock()
        mock_new_assistant.id = new_assistant_id
        mock_flow_service.create_flow_assistant.return_value = (mock_new_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        changeset = FlowChangeSet(
            flow_name="Mixed",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="step_b",
                    assistant_spec=AssistantSpec(instructions="New"),
                ),
            ],
            assistants_to_update=[
                AssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=existing_assistant_id,
                    assistant_spec=AssistantSpec(instructions="Updated"),
                ),
            ],
            assistants_to_delete=[
                AssistantToDelete(
                    step_id=uuid4(),
                    assistant_id=deleted_assistant_id,
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.MODIFIED,
                    assistant_id=existing_assistant_id,
                ),
                _compiled_step(
                    plan_step_ref="step_b",
                    step_order=2,
                    change_kind=StepChangeKind.ADDED,
                    assistant_id=None,
                ),
            ],
        )

        result = await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
        )

        # Verify all three operations happened
        assert mock_flow_service.create_flow_assistant.call_count == 1
        assert mock_flow_service.update_flow_assistant.call_count >= 1
        assert mock_flow_service.delete_flow_assistant.call_count == 1
        assert result.steps_created == 1
        assert result.steps_updated == 1
        assert result.steps_removed == 1

    @pytest.mark.asyncio
    async def test_no_model_ref_skips_model_update(self) -> None:
        """If model_ref is None, don't pass completion_model_id to update."""
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        updated_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.update_flow.return_value = updated_flow
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_update=[
                AssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=assistant_id,
                    assistant_spec=AssistantSpec(
                        instructions="Prompt",
                        model_ref=None,  # No model specified
                        knowledge_refs=[],
                    ),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                ),
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
        )

        update_kwargs = mock_flow_service.update_flow_assistant.call_args.kwargs
        assert "completion_model_id" not in update_kwargs

    @pytest.mark.asyncio
    async def test_update_without_external_resources_clears_stale_resources(
        self,
    ) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        updated_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.update_flow.return_value = updated_flow
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_update=[
                AssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=assistant_id,
                    assistant_spec=AssistantSpec(instructions="Pure text step"),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                ),
            ],
        )

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
        )

        update_kwargs = mock_flow_service.update_flow_assistant.call_args.kwargs
        assert update_kwargs["groups"] == []
        assert update_kwargs["websites"] == []
        assert update_kwargs["integration_knowledge_ids"] == []
        assert update_kwargs["mcp_server_ids"] == []
        assert update_kwargs["mcp_tools"] == []

    @pytest.mark.asyncio
    async def test_instructions_only_edit_preserves_mcp_refs_through_apply(
        self,
    ) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        step_id = uuid4()
        assistant_id = uuid4()
        mcp_server_id = uuid4()
        mcp_tool_id = uuid4()

        existing_step = _make_flow_step(
            step_id=step_id,
            flow_id=flow_id,
            assistant_id=assistant_id,
            step_order=1,
            user_description="Hämta kundärende",
        )
        current_flow = _make_flow(
            flow_id=flow_id,
            space_id=space_id,
            name="Kundärende",
            description="Hämtar ärendedata.",
            draft_revision=4,
            steps=[existing_step],
        )
        edit_result = compile_edit_draft(
            FlowEditDraft(
                operations=[
                    StepEditOperation(
                        op="modify",
                        target_ref="existing_step_1",
                        patch=StepPatch(
                            assistant_spec=AssistantSpec(
                                instructions="Hämta och sammanfatta aktuellt kundärende."
                            )
                        ),
                    )
                ],
                plan_rationale="Uppdatera instruktionen utan att ändra verktygsåtkomst.",
            ),
            [existing_step],
            base_flow_revision=4,
            flow_name=current_flow.name,
            flow_description=current_flow.description,
            assistant_snapshots={
                assistant_id: {
                    "instructions": "Hämta aktuellt kundärende.",
                    "knowledge_refs": [],
                    "mcp_server_refs": [str(mcp_server_id)],
                    "mcp_tool_refs": [str(mcp_tool_id)],
                }
            },
        )
        changeset = compile_changeset(edit_result.compiled_spec, current_flow)

        mock_flow_service = AsyncMock()
        mock_flow_service.update_flow.return_value = current_flow
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
            expected_revision=4,
        )

        update_kwargs = mock_flow_service.update_flow_assistant.call_args.kwargs
        assert update_kwargs["prompt"].text == (
            "Hämta och sammanfatta aktuellt kundärende."
        )
        assert update_kwargs["mcp_server_ids"] == [mcp_server_id]
        assert update_kwargs["mcp_tools"] == [(mcp_tool_id, True)]
        assert update_kwargs["groups"] == []
        assert update_kwargs["websites"] == []
        assert update_kwargs["integration_knowledge_ids"] == []

    @pytest.mark.asyncio
    async def test_edit_adds_mcp_step_with_step_scoped_tool_access(self) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        existing_assistant_id = uuid4()
        created_assistant_id = uuid4()
        mcp_server_id = uuid4()
        mcp_tool_id = uuid4()

        existing_step = _make_flow_step(
            flow_id=flow_id,
            assistant_id=existing_assistant_id,
            step_order=1,
            user_description="Analysera befintligt underlag",
        )
        current_flow = _make_flow(
            flow_id=flow_id,
            space_id=space_id,
            name="Ärendeanalys",
            steps=[existing_step],
            draft_revision=2,
        )
        edit_result = compile_edit_draft(
            FlowEditDraft(
                operations=[
                    StepEditOperation(
                        op="add",
                        placement=StepPlacement(position="append"),
                        add_payload=NewStepDraft(
                            name="Hämta live-data",
                            instructions="Hämta aktuell ärendedata via valt MCP-verktyg.",
                            input_source=InputSource.PREVIOUS_STEP,
                            input_type=InputType.TEXT,
                            output_type=OutputType.JSON,
                            mcp_server_refs=[str(mcp_server_id)],
                            mcp_tool_refs=[str(mcp_tool_id)],
                        ),
                    )
                ],
                plan_rationale="Lägg till live-data utan att ändra första steget.",
            ),
            [existing_step],
            base_flow_revision=2,
            flow_name=current_flow.name,
            flow_description=current_flow.description,
            assistant_snapshots={
                existing_assistant_id: {
                    "instructions": "Analysera befintligt underlag.",
                    "knowledge_refs": [],
                    "mcp_server_refs": [],
                    "mcp_tool_refs": [],
                }
            },
        )
        changeset = compile_changeset(edit_result.compiled_spec, current_flow)

        created_assistant = MagicMock()
        created_assistant.id = created_assistant_id
        mock_flow_service = AsyncMock()
        mock_flow_service.create_flow_assistant.return_value = (created_assistant, [])
        mock_flow_service.update_flow.return_value = current_flow
        mock_flow_service.update_flow_assistant.return_value = (MagicMock(), [])

        await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=space_id,
            flow_id=flow_id,
            expected_revision=2,
        )

        mcp_update_kwargs = next(
            call.kwargs
            for call in mock_flow_service.update_flow_assistant.await_args_list
            if call.kwargs["assistant_id"] == created_assistant_id
        )
        assert mcp_update_kwargs["mcp_server_ids"] == [mcp_server_id]
        assert mcp_update_kwargs["mcp_tools"] == [(mcp_tool_id, True)]
        assert mcp_update_kwargs["groups"] == []
        assert mcp_update_kwargs["websites"] == []
        assert mcp_update_kwargs["integration_knowledge_ids"] == []

    @pytest.mark.asyncio
    async def test_invalid_knowledge_ref_raises_instead_of_silently_skipping(
        self,
    ) -> None:
        flow_id = uuid4()
        space_id = uuid4()
        assistant_id = uuid4()

        mock_flow_service = AsyncMock()
        updated_flow = _make_flow(flow_id=flow_id, space_id=space_id)
        mock_flow_service.update_flow.return_value = updated_flow

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_update=[
                AssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=assistant_id,
                    assistant_spec=AssistantSpec(
                        instructions="Prompt",
                        knowledge_refs=["socio"],
                    ),
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="step_a",
                    step_order=1,
                    change_kind=StepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                ),
            ],
        )

        with pytest.raises(
            BadRequestException, match="Invalid knowledge base reference"
        ):
            await execute_changeset(
                changeset=changeset,
                flow_service=mock_flow_service,
                space_id=space_id,
                flow_id=flow_id,
            )

        mock_flow_service.update_flow_assistant.assert_not_awaited()


# ---------------------------------------------------------------------------
# Executor: result counting
# ---------------------------------------------------------------------------


class TestExecuteResultCounting:
    @pytest.mark.asyncio
    async def test_counts_created_steps(self) -> None:
        mock_flow_service = AsyncMock()
        mock_flow_service.create_flow.return_value = _make_flow()
        mock_assistant = MagicMock()
        mock_assistant.id = uuid4()
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="s1", assistant_spec=AssistantSpec(instructions="x")
                ),
                AssistantToCreate(
                    plan_step_ref="s2", assistant_spec=AssistantSpec(instructions="y")
                ),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="s1", step_order=1, change_kind=StepChangeKind.ADDED
                ),
                _compiled_step(
                    plan_step_ref="s2", step_order=2, change_kind=StepChangeKind.ADDED
                ),
            ],
        )

        result = await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=uuid4(),
            flow_id=None,
        )
        assert result.steps_created == 2
        assert result.steps_updated == 0
        assert result.steps_removed == 0

    @pytest.mark.asyncio
    async def test_counts_all_change_kinds(self) -> None:
        mock_flow_service = AsyncMock()
        mock_flow_service.update_flow.return_value = _make_flow()
        mock_assistant = MagicMock()
        mock_assistant.id = uuid4()
        mock_flow_service.create_flow_assistant.return_value = (mock_assistant, [])
        mock_flow_service.update_flow_assistant.return_value = (mock_assistant, [])

        changeset = FlowChangeSet(
            flow_name="Test",
            flow_description="",
            assistants_to_create=[
                AssistantToCreate(
                    plan_step_ref="new", assistant_spec=AssistantSpec(instructions="x")
                ),
            ],
            assistants_to_update=[
                AssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=uuid4(),
                    assistant_spec=AssistantSpec(instructions="y"),
                ),
            ],
            assistants_to_delete=[
                AssistantToDelete(step_id=uuid4(), assistant_id=uuid4()),
                AssistantToDelete(step_id=uuid4(), assistant_id=uuid4()),
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="mod",
                    step_order=1,
                    change_kind=StepChangeKind.MODIFIED,
                    assistant_id=uuid4(),
                ),
                _compiled_step(
                    plan_step_ref="new", step_order=2, change_kind=StepChangeKind.ADDED
                ),
            ],
        )

        result = await execute_changeset(
            changeset=changeset,
            flow_service=mock_flow_service,
            space_id=uuid4(),
            flow_id=uuid4(),
        )
        assert result.steps_created == 1
        assert result.steps_updated == 1
        assert result.steps_removed == 2


# ---------------------------------------------------------------------------
# Helpers for compiled steps
# ---------------------------------------------------------------------------


def _compiled_step(
    *,
    plan_step_ref: str = "step_a",
    step_order: int = 1,
    change_kind: StepChangeKind = StepChangeKind.ADDED,
    user_description: str | None = "Test step",
    assistant_id: UUID | None = None,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    mcp_policy: str = "inherit",
    input_bindings: dict | None = None,
    review_policy: FlowStepReviewPolicy | None = None,
) -> Any:
    from intric.flows.ai_builder.ai_builder_models import CompiledStep

    return CompiledStep(
        plan_step_ref=plan_step_ref,
        step_order=step_order,
        change_kind=change_kind,
        user_description=user_description,
        assistant_id=assistant_id,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy=mcp_policy,
        input_bindings=input_bindings,
        review_policy=review_policy,
    )
