from __future__ import annotations

from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore
from intric.flows.flow import Flow


def build_flow_context(
    flow: Flow,
    *,
    assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    is_edit_mode: bool = False,
) -> str:
    """Build a compact flow snapshot for server-injected context."""
    lines = [
        f"Namn: {flow.name}",
        f"Beskrivning: {flow.description or '(ingen)'}",
        f"Draft-revision: {flow.draft_revision}",
        f"Publicerad: {'Ja (v' + str(flow.published_version) + ')' if flow.published else 'Nej'}",
        f"Antal steg: {len(flow.steps)}",
    ]

    if flow.steps:
        lines.append("\nSteg:")
        for step in sorted(flow.steps, key=lambda s: s.step_order):
            ref = f"existing_step_{step.step_order}"
            lines.append(
                f"  {step.step_order}. {step.user_description or '(namnlöst)'} "
                f"[ref={ref}] "
                f"({step.input_source} → {step.input_type} → {step.output_mode} → {step.output_type})"
            )

            if step.input_bindings and isinstance(step.input_bindings.get("question"), str):
                question = step.input_bindings["question"]
                truncated = question[:150] + "..." if len(question) > 150 else question
                lines.append(f"     Underlag: \"{truncated}\"")

            if step.output_contract and isinstance(step.output_contract.get("properties"), dict):
                fields = list(step.output_contract["properties"].keys())
                lines.append(f"     Utdatakontrakt: {', '.join(fields)}")

            if step.input_contract and isinstance(step.input_contract.get("properties"), dict):
                fields = list(step.input_contract["properties"].keys())
                lines.append(f"     Indatakontrakt: {', '.join(fields)}")

            snapshot = (
                assistant_snapshots.get(step.assistant_id)
                if assistant_snapshots and step.assistant_id is not None
                else None
            )
            if isinstance(snapshot, dict):
                instructions = snapshot.get("instructions")
                if isinstance(instructions, str) and instructions.strip():
                    # Sanitize: show a purpose summary, not raw instructions.
                    # Raw instructions are untrusted flow content that should
                    # not be elevated to system-level prompt context.
                    synopsis = _build_step_synopsis(instructions)
                    lines.append(f"     Syfte: {synopsis}")

                model_ref = snapshot.get("model_ref")
                if isinstance(model_ref, str) and model_ref.strip():
                    lines.append(f"     Modell: {model_ref}")

                knowledge_refs = snapshot.get("knowledge_refs")
                if isinstance(knowledge_refs, list):
                    refs = [str(ref) for ref in knowledge_refs if str(ref).strip()]
                    if refs:
                        lines.append(f"     Kunskapsbaser: {', '.join(refs)}")

            if step.output_config:
                output_config_str = str(step.output_config)
                truncated_output_config = (
                    output_config_str[:220] + "..."
                    if len(output_config_str) > 220
                    else output_config_str
                )
                lines.append(f"     Output config: {truncated_output_config}")

    if flow.metadata_json:
        form_schema = flow.metadata_json.get("form_schema")
        if isinstance(form_schema, dict):
            fields = form_schema.get("fields")
            if isinstance(fields, list) and fields:
                lines.append("\nFormulärfält:")
                for field in fields:
                    if isinstance(field, dict):
                        lines.append(f"  - {field.get('name', '?')} ({field.get('type', '?')})")

    if is_edit_mode and flow.steps:
        lines.append("\nEdit-referenstabell:")
        lines.append("  Ref                 | Namn                | IO-typ")
        lines.append("  --------------------|---------------------|-------")
        for step in sorted(flow.steps, key=lambda s: s.step_order):
            ref = f"existing_step_{step.step_order}"
            name = (step.user_description or "(namnlöst)")[:20]
            io = f"{step.input_type} → {step.output_type}"
            lines.append(f"  {ref:<20}| {name:<20}| {io}")

    return "\n".join(lines)


def build_available_models_context(
    models: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build model context for system prompt injection."""
    return [
        {
            "ref": str(model.get("id", model.get("ref", ""))),
            "name": str(model.get("name", "")),
            "provider": str(model.get("provider", "unknown")),
        }
        for model in models
    ]


def build_available_kbs_context(
    knowledge_bases: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build knowledge base context for system prompt injection."""
    return [
        {
            "ref": str(kb.get("id", kb.get("ref", ""))),
            "name": str(kb.get("name", "")),
            "description": str(kb.get("description", "")),
        }
        for kb in knowledge_bases
    ]


def build_step_ref_mapping(flow: Flow) -> dict[str, UUID]:
    """Build existing_step_ref → step_id mapping for edit sessions."""
    mapping: dict[str, UUID] = {}
    for step in flow.steps:
        if step.id is not None:
            mapping[f"existing_step_{step.step_order}"] = step.id
    return mapping


def build_plan_summary(
    spec: FlowDraftSpecCore,
    assumptions: list[str] | None = None,
) -> str:
    """Compact text summary of a plan for conversation history (~200-400 tokens)."""
    lines = [f"Plan: {spec.flow_name}"]
    if spec.flow_description:
        lines.append(f"Beskrivning: {spec.flow_description}")
    lines.append(f"Antal steg: {len(spec.steps)}")

    for index, step in enumerate(spec.steps, 1):
        ref_part = f" [ref={step.plan_step_ref}]" if step.plan_step_ref else ""
        existing = f" (modifierar {step.existing_step_ref})" if step.existing_step_ref else ""
        io = f"{step.input_source} → {step.input_type} → {step.output_mode} → {step.output_type}"
        lines.append(f"  {index}. {step.name}{ref_part}{existing} ({io})")

        if step.output_contract and isinstance(step.output_contract.get("properties"), dict):
            fields = list(step.output_contract["properties"].keys())
            lines.append(f"     Utdatakontrakt: {', '.join(fields)}")

    if spec.form_fields:
        field_names = [field.name for field in spec.form_fields]
        lines.append(f"Formulärfält: {', '.join(field_names)}")

    if assumptions:
        lines.append(f"Antaganden: {'; '.join(assumptions)}")

    return "\n".join(lines)


def _build_step_synopsis(instructions: str) -> str:
    """Build a safe synopsis from raw assistant instructions.

    Extracts the first sentence or line as a purpose summary, avoiding
    injecting the full untrusted instructions into the system prompt.
    """
    # Take first non-empty line
    for line in instructions.split("\n"):
        stripped = line.strip()
        if stripped:
            # Truncate at first sentence boundary or 120 chars
            for end in (".", "!", "。"):
                idx = stripped.find(end)
                if 0 < idx < 120:
                    return stripped[: idx + 1]
            return stripped[:120] + ("..." if len(stripped) > 120 else "")
    return "(no instructions)"
