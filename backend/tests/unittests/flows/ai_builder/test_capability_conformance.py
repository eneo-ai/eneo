"""Every cell the Builder may propose is a flow the platform accepts.

The table names one flow per proposable (input type, output type, output mode)
triple. Set equality with the manifest's proposable_new projection fails the
suite when the manifest grows a triple that has no flow here, and when a flow
here names a triple the manifest no longer proposes.
"""

from __future__ import annotations

import pytest

from eneo.flows.enums import FlowAuthoringInputSource
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_capability_manifest import CapabilityProjection, projection_cells
from eneo.flows.flow_validators import collect_step_graph_issues
from tests.unittests.flows.ai_builder.authoring_command_assertions import (
    assert_create_spec_materializes_through_authoring_command_async,
    assert_create_spec_prepares_through_authoring_command_async,
)

Triple = tuple[str, str, str]

# (input type, output type, output mode), written out so that a new proposable
# triple has to be added here by hand.
PROPOSABLE_TRIPLES: tuple[Triple, ...] = (
    ("text", "text", "pass_through"),
    ("text", "text", "compose_text"),
    ("text", "json", "pass_through"),
    ("text", "pdf", "render_verbatim"),
    ("text", "docx", "render_verbatim"),
    ("text", "docx", "template_fill"),
    ("json", "text", "pass_through"),
    ("json", "json", "pass_through"),
    ("json", "pdf", "pass_through"),
    ("json", "docx", "pass_through"),
    ("json", "docx", "template_fill"),
    ("audio", "text", "pass_through"),
    ("audio", "text", "transcribe_only"),
    ("audio", "json", "pass_through"),
    ("audio", "pdf", "pass_through"),
    ("audio", "docx", "pass_through"),
    ("audio", "docx", "template_fill"),
    ("document", "text", "pass_through"),
    ("document", "json", "pass_through"),
    ("document", "pdf", "pass_through"),
    ("document", "docx", "pass_through"),
    ("document", "docx", "template_fill"),
    ("file", "text", "pass_through"),
    ("file", "json", "pass_through"),
    ("file", "pdf", "pass_through"),
    ("file", "docx", "pass_through"),
    ("file", "docx", "template_fill"),
    ("any", "text", "pass_through"),
    ("any", "json", "pass_through"),
    ("any", "pdf", "pass_through"),
    ("any", "docx", "pass_through"),
    ("any", "docx", "template_fill"),
)


def _step(
    ref: str,
    triple: Triple,
    *,
    source: FlowAuthoringInputSource = FlowAuthoringInputSource.FLOW_INPUT,
) -> StepSpec:
    input_type, output_type, output_mode = triple
    return StepSpec(
        plan_step_ref=ref,
        name=f"Steg {ref}",
        assistant_spec=AssistantSpec(
            instructions="Hantera underlaget och leverera resultatet."
        ),
        input_source=source,
        input_type=InputType(input_type),
        output_type=OutputType(output_type),
        output_mode=OutputMode(output_mode),
    )


def conformance_flow(triple: Triple) -> FlowDraftSpecCore:
    """A flow the platform accepts that contains the triple as a step.

    An audio step reads the flow input, and only one step may. The platform
    refuses a flow whose first step is audio and whose last step is a document
    unless that first step is a transcription, so an audio step that itself
    produces a document is only accepted ahead of a text-producing last step.
    """
    input_type, output_type, _mode = triple
    steps = [_step("step_a", triple)]
    if input_type == "audio" and output_type in {"pdf", "docx"}:
        steps.append(
            _step(
                "step_b",
                ("text", "text", "pass_through"),
                source=FlowAuthoringInputSource.PREVIOUS_STEP,
            )
        )
    return FlowDraftSpecCore(flow_name=f"Konformans {'-'.join(triple)}", steps=steps)


def test_one_flow_per_proposable_triple() -> None:
    projected = {
        (cell[1].value, cell[2].value, cell[3].value)
        for cell in projection_cells(CapabilityProjection.PROPOSABLE_NEW)
    }
    assert len(PROPOSABLE_TRIPLES) == len(set(PROPOSABLE_TRIPLES)) == 32
    assert set(PROPOSABLE_TRIPLES) == projected


@pytest.mark.asyncio
@pytest.mark.parametrize("triple", PROPOSABLE_TRIPLES, ids="-".join)
async def test_a_proposable_triple_prepares_applies_and_validates(
    triple: Triple,
) -> None:
    spec = conformance_flow(triple)
    await assert_create_spec_prepares_through_authoring_command_async(spec)
    flow = await assert_create_spec_materializes_through_authoring_command_async(spec)

    assert collect_step_graph_issues(flow.steps, metadata_json=flow.metadata_json) == []
