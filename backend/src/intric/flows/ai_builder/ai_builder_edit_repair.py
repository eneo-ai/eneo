"""Constrained description repair for compiled AI Builder edit proposals."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    description_hash,
)
from intric.flows.ai_builder.ai_builder_edit_models import EditAdvisory
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ProposalCompletionFn,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)


def should_attempt_description_repair(
    *,
    advisories: list[EditAdvisory],
    current_description: str | None,
    current_provenance: DescriptionProvenance | None,
) -> bool:
    if not any(a.code == "flow_description_update_required" for a in advisories):
        return False

    if current_provenance is None:
        return False

    if current_provenance.mode != "builder_managed":
        return False

    if current_provenance.last_generated_hash is None:
        return False

    current_hash = description_hash(current_description)
    return current_hash == current_provenance.last_generated_hash


def extract_description_provenance(
    metadata_json: dict[str, Any] | None,
) -> DescriptionProvenance | None:
    if not isinstance(metadata_json, dict):
        return None
    ai_builder = metadata_json.get("ai_builder")
    if not isinstance(ai_builder, dict):
        return None
    desc_raw = cast(dict[str, Any], ai_builder).get("description")
    if not isinstance(desc_raw, dict):
        return None
    try:
        return DescriptionProvenance.model_validate(desc_raw)
    except Exception:
        return None


def validate_repair_invariance(
    original_spec: FlowDraftSpecCore,
    repaired_spec: FlowDraftSpecCore,
) -> bool:
    zeroed_original = original_spec.model_copy(update={"flow_description": ""})
    zeroed_repaired = repaired_spec.model_copy(update={"flow_description": ""})
    return zeroed_original.spec_hash() == zeroed_repaired.spec_hash()


async def attempt_description_repair(
    *,
    call_proposal_completion: ProposalCompletionFn,
    compiled_spec: FlowDraftSpecCore,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
) -> FlowDraftSpecCore | None:
    repair_prompt = (
        "The flow's input or output type changed but the description was not updated. "
        "Generate ONLY a new flow_description that accurately reflects the current flow. "
        f"Current flow name: {compiled_spec.flow_name}\n"
        f"Current description (stale): {compiled_spec.flow_description}\n"
        f"Steps: {', '.join(s.name for s in compiled_spec.steps)}\n"
        f"Entry input: {compiled_spec.steps[0].input_type.value if compiled_spec.steps else 'none'}\n"
        f"Terminal output: {compiled_spec.steps[-1].output_type.value if compiled_spec.steps else 'none'}\n"
        "Respond with ONLY the new description text, nothing else."
    )

    try:
        response = await call_proposal_completion(
            messages=[{"role": "user", "content": repair_prompt}],
            tool_schemas=[],
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            temperature=0.3,
        )
        new_description = (response.choices[0].message.content or "").strip()
        if not new_description:
            return None

        repaired = compiled_spec.model_copy(
            update={"flow_description": new_description}
        )
        if not validate_repair_invariance(compiled_spec, repaired):
            logger.warning(
                "Description repair changed non-description fields, rejecting"
            )
            return None

        return repaired
    except Exception as exc:
        logger.warning("Description repair failed: %s", exc)
        return None


async def repair_compiled_edit_description_if_needed(
    *,
    compiled: CompiledProposal,
    flow: "Flow | None",
    call_proposal_completion: ProposalCompletionFn,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
) -> CompiledProposal:
    if flow is None or compiled.edit_result is None:
        return compiled
    edit_result = compiled.edit_result.compiled_edit
    if edit_result is None:
        return compiled
    current_provenance = extract_description_provenance(flow.metadata_json)
    if not should_attempt_description_repair(
        advisories=edit_result.advisories,
        current_description=flow.description,
        current_provenance=current_provenance,
    ):
        return compiled

    repaired_spec = await attempt_description_repair(
        call_proposal_completion=call_proposal_completion,
        compiled_spec=compiled.spec,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        max_output_tokens=min(max_output_tokens, 256),
    )
    if repaired_spec is None:
        return compiled

    repaired_edit = edit_result.model_copy(
        update={
            "compiled_spec": repaired_spec,
            "advisories": [
                advisory
                for advisory in edit_result.advisories
                if advisory.code != "flow_description_update_required"
            ],
        }
    )
    return replace(
        compiled,
        spec=repaired_spec,
        edit_result=compiled.edit_result.model_copy(
            update={"compiled_edit": repaired_edit}
        ),
    )
