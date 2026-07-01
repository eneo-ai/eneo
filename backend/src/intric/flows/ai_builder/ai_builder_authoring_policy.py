from __future__ import annotations

import re

from intric.flows.application.flow_authoring_command import AIBuilderFlowAuthoringOrigin
from intric.flows.application.flow_authoring_description_semantics import (
    FlowSemanticSignature,
)
from intric.flows.application.flow_draft_materialization import FlowDraftChangeSet
from intric.flows.domain.flow import (
    Flow,
    FlowPersistedJsonObject,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
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
    ) -> FlowDraftChangeSet:
        metadata = _stamp_ai_builder_metadata(
            metadata=changeset.metadata_json,
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
        old_sig = FlowSemanticSignature.from_flow_steps(current_flow.steps)
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
    origin: AIBuilderFlowAuthoringOrigin,
) -> FlowPersistedJsonObject:
    result = dict(metadata or {})
    result["ai_builder"] = {
        "origin": {
            "builder_session_id": str(origin.session_id),
            "builder_plan_id": str(origin.plan_id),
            "builder_spec_hash": origin.spec_hash,
            "applied_at": origin.applied_at.isoformat(),
        }
    }
    return result
