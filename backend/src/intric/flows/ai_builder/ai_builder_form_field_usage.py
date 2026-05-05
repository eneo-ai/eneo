"""Form-field usage predicate consumed by the AI Builder critic."""

from __future__ import annotations

import json

from intric.flows.ai_builder.ai_builder_domain_models import (
    FlowDraftSpecCore,
    StepSpec,
)
from intric.flows.template_reference_analyzer import (
    analyze_template,
    referenced_form_fields,
)


def _iter_step_templates(step: StepSpec) -> list[str]:
    templates = [step.assistant_spec.instructions]
    for payload in (step.input_bindings, step.output_config):
        if payload is None:
            continue
        templates.append(json.dumps(payload, ensure_ascii=False))
    return templates


def find_unused_form_fields(spec: FlowDraftSpecCore) -> list[str]:
    declared_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    if not declared_fields:
        return []

    used_fields: set[str] = set()
    for step in spec.steps:
        for template in _iter_step_templates(step):
            refs = analyze_template(
                template,
                step_refs={},
                form_field_names=declared_fields,
            )
            used_fields.update(referenced_form_fields(refs))
    return sorted(declared_fields - used_fields)


__all__ = ["find_unused_form_fields"]
