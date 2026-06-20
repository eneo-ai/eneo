from __future__ import annotations

import re

from intric.flows.application.flow_authoring_command import AIBuilderFlowAuthoringOrigin
from intric.flows.application.flow_authoring_description_semantics import (
    DescriptionProvenance,
    FlowSemanticSignature,
    description_hash,
)
from intric.flows.application.flow_draft_materialization import FlowDraftChangeSet
from intric.flows.domain.flow import (
    Flow,
    FlowPersistedJsonObject,
    FlowStep,
    clone_json_object,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


class AIBuilderAuthoringPolicy:
    def __init__(self, origin: AIBuilderFlowAuthoringOrigin) -> None:
        self._origin = origin

    def effective_spec(
        self,
        *,
        spec: FlowDraftSpecCore,
        current_flow: Flow | None,
    ) -> FlowDraftSpecCore:
        resolved_description = _resolve_flow_description(
            spec=spec,
            current_flow=current_flow,
            description_override_manual=self._origin.description_override_manual,
        )
        if resolved_description == spec.flow_description:
            return spec
        return spec.model_copy(update={"flow_description": resolved_description})

    def stamp_metadata(
        self,
        *,
        changeset: FlowDraftChangeSet,
        spec: FlowDraftSpecCore,
    ) -> FlowDraftChangeSet:
        metadata = _stamp_ai_builder_metadata(
            metadata=changeset.metadata_json,
            spec=spec,
            origin=self._origin,
        )
        return changeset.model_copy(update={"metadata_json": metadata})


def _resolve_flow_description(
    *,
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    description_override_manual: bool,
) -> str:
    if current_flow is None or description_override_manual:
        return spec.flow_description

    current_description = current_flow.description or ""
    if spec.flow_description != current_description:
        return spec.flow_description

    try:
        old_sig = FlowSemanticSignature.from_steps(
            _flow_steps_to_step_specs(current_flow.steps)
        )
    except ValueError:
        return spec.flow_description
    new_sig = FlowSemanticSignature.from_steps(spec.steps)
    if old_sig == new_sig:
        return spec.flow_description

    return _rewrite_terminal_output_phrase(
        description=current_description,
        old_output_type=old_sig.terminal_output_type,
        new_output_type=new_sig.terminal_output_type,
    )


def _flow_steps_to_step_specs(steps: list[FlowStep]) -> list[StepSpec]:
    return [
        StepSpec(
            plan_step_ref=f"existing_step_{step.step_order}",
            name=step.user_description or f"Step {step.step_order}",
            assistant_spec=AssistantSpec(instructions=""),
            input_source=InputSource(step.input_source.value),
            input_type=InputType(step.input_type.value),
            output_mode=OutputMode(step.output_mode.value),
            output_type=OutputType(step.output_type.value),
            input_bindings=step.input_bindings,
            input_contract=step.input_contract,
            output_contract=step.output_contract,
            input_config=step.input_config,
            output_config=step.output_config,
            mcp_policy=step.mcp_policy,
        )
        for step in steps
    ]


def _rewrite_terminal_output_phrase(
    *,
    description: str,
    old_output_type: str | None,
    new_output_type: str | None,
) -> str:
    output_labels = {
        "text": "text",
        "docx": "DOCX",
        "pdf": "PDF",
        "json": "JSON",
    }
    old_label = output_labels.get(old_output_type or "")
    new_label = output_labels.get(new_output_type or "")
    if old_label is None or new_label is None or old_label == new_label:
        return description

    format_pattern = re.compile(
        rf"\bi\s+{re.escape(old_label)}-?format\b",
        flags=re.IGNORECASE,
    )
    if format_pattern.search(description):
        return format_pattern.sub(f"i {new_label}-format", description)
    return description


def _stamp_ai_builder_metadata(
    *,
    metadata: FlowPersistedJsonObject | None,
    spec: FlowDraftSpecCore,
    origin: AIBuilderFlowAuthoringOrigin,
) -> FlowPersistedJsonObject:
    result = dict(metadata or {})
    raw_ai_builder = result.get("ai_builder")
    ai_builder = clone_json_object(raw_ai_builder) or {}
    ai_builder["description"] = _description_provenance(
        spec=spec,
        description_override_manual=origin.description_override_manual,
    ).model_dump(mode="json")
    ai_builder["origin"] = {
        "builder_session_id": str(origin.session_id),
        "builder_plan_id": str(origin.plan_id),
        "builder_spec_hash": origin.spec_hash,
        "applied_at": origin.applied_at.isoformat(),
    }
    result["ai_builder"] = ai_builder
    return result


def _description_provenance(
    *,
    spec: FlowDraftSpecCore,
    description_override_manual: bool,
) -> DescriptionProvenance:
    if description_override_manual:
        return DescriptionProvenance(mode="manual")
    return DescriptionProvenance(
        mode="builder_managed",
        semantic_signature=FlowSemanticSignature.from_steps(spec.steps),
        last_generated_hash=description_hash(spec.flow_description),
    )
