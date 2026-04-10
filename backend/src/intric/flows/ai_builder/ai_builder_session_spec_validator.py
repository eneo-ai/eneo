from __future__ import annotations

import re

from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    StepSpec,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult

_EXISTING_STEP_REF_RE = re.compile(r"^existing_step_[1-9]\d*$")


def normalize_compiled_spec_for_session(
    spec: FlowDraftSpecCore,
    *,
    target_kind: TargetKind,
) -> FlowDraftSpecCore:
    if target_kind != TargetKind.CREATE:
        return spec

    normalized_steps: list[StepSpec] = []
    changed = False
    for step in spec.steps:
        if step.existing_step_ref is None:
            normalized_steps.append(step)
            continue
        normalized_steps.append(step.model_copy(update={"existing_step_ref": None}))
        changed = True

    if not changed:
        return spec

    return spec.model_copy(update={"steps": normalized_steps})


def validate_compiled_spec_for_session(
    spec: FlowDraftSpecCore,
    *,
    target_kind: TargetKind,
    valid_existing_step_refs: list[str] | None,
) -> SpecValidationResult:
    result = SpecValidationResult()
    seen_existing_refs: set[str] = set()

    for step in spec.steps:
        existing_step_ref = step.existing_step_ref
        if existing_step_ref is None:
            continue

        if target_kind == TargetKind.CREATE:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_existing_step_ref",
                message=(
                    f"Step '{step.plan_step_ref}' cannot set existing_step_ref "
                    f"'{existing_step_ref}' in create mode."
                ),
            )
            continue

        if not _EXISTING_STEP_REF_RE.match(existing_step_ref):
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_existing_step_ref",
                message=(
                    f"Step '{step.plan_step_ref}' uses invalid existing_step_ref "
                    f"'{existing_step_ref}'. Expected the server alias format "
                    f"'existing_step_N'."
                ),
            )
            continue

        if (
            valid_existing_step_refs is not None
            and existing_step_ref not in valid_existing_step_refs
        ):
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_existing_step_ref",
                message=(
                    f"Step '{step.plan_step_ref}' references unknown existing_step_ref "
                    f"'{existing_step_ref}'. Valid refs: {valid_existing_step_refs}"
                ),
            )
            continue

        if existing_step_ref in seen_existing_refs:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_existing_step_ref",
                message=(
                    f"Step '{step.plan_step_ref}' reuses existing_step_ref "
                    f"'{existing_step_ref}'. Each existing step can only be targeted once."
                ),
            )
            continue

        seen_existing_refs.add(existing_step_ref)

    return result
