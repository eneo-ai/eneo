"""Form-field usage predicate consumed by the AI Builder critic."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_validation_references import (
    iter_step_templates,
)
from eneo.flows.domain.speaker_mapping_config import (
    speaker_mapping_participants_field,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    StepSpec,
)
from eneo.flows.template_reference_analyzer import (
    analyze_template,
    referenced_form_fields,
)


def step_references_form_field(spec: FlowDraftSpecCore, step: StepSpec) -> bool:
    declared_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    if not declared_fields:
        return False

    step_refs = {
        candidate.plan_step_ref: index for index, candidate in enumerate(spec.steps)
    }
    for template in iter_step_templates(step):
        refs = analyze_template(
            template,
            step_refs=step_refs,
            form_field_names=declared_fields,
        )
        if referenced_form_fields(refs):
            return True
    return False


def find_unused_form_fields(spec: FlowDraftSpecCore) -> list[str]:
    declared_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    if not declared_fields:
        return []

    used_fields: set[str] = set()
    for step in spec.steps:
        # A speaker-naming step reads its participant list by field name.
        participants_field = speaker_mapping_participants_field(step.output_config)
        if participants_field is not None:
            used_fields.add(participants_field.strip())
        for template in iter_step_templates(step):
            refs = analyze_template(
                template,
                step_refs={},
                form_field_names=declared_fields,
            )
            used_fields.update(referenced_form_fields(refs))
    return sorted(declared_fields - used_fields)


__all__ = ["find_unused_form_fields", "step_references_form_field"]
