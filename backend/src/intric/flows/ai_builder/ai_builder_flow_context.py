from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    FlowCapabilityProfile,
    build_flow_capability_profile,
)
from intric.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshots,
)
from intric.flows.domain.flow import Flow, FlowStep, JsonObject
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_edit_scope import EditScopeResolution


def build_flow_context(
    flow: Flow,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    is_edit_mode: bool = False,
    capabilities: FlowCapabilityProfile | None = None,
    edit_scope: "EditScopeResolution | None" = None,
) -> str:
    """Build a compact flow snapshot for server-injected context."""
    if is_edit_mode:
        return _build_edit_mode_flow_context(
            flow,
            assistant_snapshots=assistant_snapshots,
            capabilities=capabilities or build_flow_capability_profile(flow),
            edit_scope=edit_scope,
        )
    return _build_detailed_flow_context(
        flow,
        assistant_snapshots=assistant_snapshots,
        is_edit_mode=is_edit_mode,
    )


def _build_detailed_flow_context(
    flow: Flow,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    is_edit_mode: bool = False,
) -> str:
    sorted_steps = sorted(flow.steps, key=lambda step: step.step_order)
    lines = [
        f"Namn: {flow.name}",
        f"Beskrivning: {flow.description or '(ingen)'}",
        f"Draft-revision: {flow.draft_revision}",
        f"Publicerad: {'Ja (v' + str(flow.published_version) + ')' if flow.published else 'Nej'}",
        f"Antal steg: {len(sorted_steps)}",
    ]

    if sorted_steps:
        lines.append("\nSteg:")
        for step in sorted_steps:
            ref = f"existing_step_{step.step_order}"
            lines.append(
                f"  {step.step_order}. {step.user_description or '(namnlöst)'} "
                f"[ref={ref}] "
                f"({step.input_source} → {step.input_type} → {step.output_mode} → {step.output_type})"
            )

            if step.input_bindings and isinstance(
                step.input_bindings.get("question"), str
            ):
                question = step.input_bindings["question"]
                truncated = question[:150] + "..." if len(question) > 150 else question
                lines.append(f'     Underlag: "{truncated}"')

            if step.output_contract and isinstance(
                step.output_contract.get("properties"), dict
            ):
                fields = list(step.output_contract["properties"].keys())
                lines.append(f"     Utdatakontrakt: {', '.join(fields)}")

            if step.input_contract and isinstance(
                step.input_contract.get("properties"), dict
            ):
                fields = list(step.input_contract["properties"].keys())
                lines.append(f"     Indatakontrakt: {', '.join(fields)}")

            snapshot = (
                assistant_snapshots.get(step.assistant_id)
                if assistant_snapshots
                else None
            )
            if snapshot is not None:
                if snapshot.instructions:
                    # Sanitize: show a purpose summary, not raw instructions.
                    # Raw instructions are untrusted flow content that should
                    # not be elevated to system-level prompt context.
                    synopsis = _build_step_synopsis(snapshot.instructions)
                    lines.append(f"     Syfte: {synopsis}")

                if snapshot.model is not None:
                    lines.append(f"     Modell: {snapshot.model.display_value}")

                knowledge_values = _display_snapshot_resources(snapshot.knowledge_refs)
                if knowledge_values:
                    lines.append(f"     Kunskapsbaser: {', '.join(knowledge_values)}")

                mcp_tool_values = _display_snapshot_resources(snapshot.mcp_tool_refs)
                if mcp_tool_values:
                    lines.append(f"     MCP-verktyg: {', '.join(mcp_tool_values)}")

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
            fields = cast(JsonObject, form_schema).get("fields")
            if isinstance(fields, list) and fields:
                lines.append("\nFormulärfält:")
                for field in cast(list[object], fields):
                    if isinstance(field, dict):
                        field_dict = cast(JsonObject, field)
                        lines.append(
                            f"  - {field_dict.get('name', '?')} ({field_dict.get('type', '?')})"
                        )

    if is_edit_mode and sorted_steps:
        lines.append("\nEdit-referenstabell:")
        lines.append("  Ref                 | Namn                | IO-typ")
        lines.append("  --------------------|---------------------|-------")
        for step in sorted_steps:
            ref = f"existing_step_{step.step_order}"
            name = (step.user_description or "(namnlöst)")[:20]
            io = f"{step.input_type} → {step.output_type}"
            lines.append(f"  {ref:<20}| {name:<20}| {io}")

    return "\n".join(lines)


def _build_edit_mode_flow_context(
    flow: Flow,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    capabilities: FlowCapabilityProfile,
    edit_scope: "EditScopeResolution | None",
) -> str:
    steps = sorted(flow.steps, key=lambda step: step.step_order)
    lines = [
        f"Namn: {flow.name}",
        f"Beskrivning: {flow.description or '(ingen)'}",
        "",
        "## Flödets nuvarande profil",
        f"- Indata: {_describe_input_profile(capabilities)}",
        f"- Utdata: {_describe_output_profile(capabilities, steps)}",
    ]

    form_fields = _form_field_names(flow)
    if form_fields:
        lines.append(f"- Formulär: {', '.join(form_fields)}")

    contract_steps = _format_step_ranges(capabilities.contract_step_orders)
    if contract_steps:
        lines.append(f"- Kontrakt: {contract_steps}")

    kb_summary = _knowledge_base_summary(steps, assistant_snapshots)
    if kb_summary:
        lines.append(f"- Kunskapsbaser: {kb_summary}")

    citation_summary = _format_step_ranges(capabilities.citation_step_orders)
    if citation_summary:
        lines.append(f"- Källhänvisningar: {citation_summary}")

    if capabilities.variable_binding_step_orders:
        lines.append(
            f"- Variabelbindningar: {_format_step_ranges(capabilities.variable_binding_step_orders)}"
        )

    if edit_scope is not None:
        lines.extend(
            [
                "",
                "## Den här redigeringen",
                f"- Aktiv familj: {_format_active_families(edit_scope)}",
            ]
        )
        requested_change = _format_requested_output_change(
            capabilities=capabilities,
            edit_scope=edit_scope,
        )
        if requested_change:
            lines.append(f"- Begärd ändring: {requested_change}")
        unresolved_decision = _format_unresolved_output_decision(edit_scope)
        if unresolved_decision:
            lines.append(f"- Olöst beslut: {unresolved_decision}")

    if steps:
        lines.extend(
            [
                "",
                "## Stegöversikt",
                "Ref | Namn | IO",
                "--- | --- | ---",
            ]
        )
        for step in steps:
            ref = f"existing_step_{step.step_order}"
            name = step.user_description or "(namnlöst)"
            io = (
                f"{getattr(step.input_source, 'value', step.input_source)} -> "
                f"{getattr(step.input_type, 'value', step.input_type)} -> "
                f"{getattr(step.output_mode, 'value', step.output_mode)} -> "
                f"{getattr(step.output_type, 'value', step.output_type)}"
            )
            lines.append(f"{ref} | {name} | {io}")

    return "\n".join(lines)


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
        existing = (
            f" (modifierar {step.existing_step_ref})" if step.existing_step_ref else ""
        )
        io = f"{step.input_source} → {step.input_type} → {step.output_mode} → {step.output_type}"
        lines.append(f"  {index}. {step.name}{ref_part}{existing} ({io})")

        if step.output_contract and isinstance(
            step.output_contract.get("properties"), dict
        ):
            fields = list(step.output_contract["properties"].keys())
            lines.append(f"     Utdatakontrakt: {', '.join(fields)}")

    if spec.form_fields:
        field_names = [field.name for field in spec.form_fields]
        lines.append(f"Formulärfält: {', '.join(field_names)}")

    if assumptions:
        lines.append(f"Antaganden: {'; '.join(assumptions)}")

    return "\n".join(lines)


def _describe_input_profile(capabilities: FlowCapabilityProfile) -> str:
    if not capabilities.flow_input_steps:
        return "ingen definierad runtime-indata ännu"

    first_entry = capabilities.flow_input_steps[0]
    if capabilities.runtime_input_mode in {"documents", "text_and_documents"}:
        descriptor = f"dokument via steg {first_entry.step_order}"
        if first_entry.max_files is not None:
            suffix = (
                "definierad runtime-uppladdning, flera filer"
                if first_entry.max_files > 1
                else "definierad runtime-uppladdning, en fil"
            )
            return f"{descriptor} ({suffix})"
        return f"{descriptor} (definierad runtime-uppladdning)"
    if capabilities.runtime_input_mode == "audio":
        return f"ljud via steg {first_entry.step_order}"
    if capabilities.runtime_input_mode == "text":
        return f"text via steg {first_entry.step_order}"
    if capabilities.runtime_input_mode == "mixed":
        return "blandad runtime-indata via flera entry-steg"
    return f"flera entry-steg ({', '.join(str(step.step_order) for step in capabilities.flow_input_steps)})"


def _describe_output_profile(
    capabilities: FlowCapabilityProfile,
    steps: list[FlowStep],
) -> str:
    if capabilities.final_output_type is None:
        return "inte definierad ännu"
    final_step_order = steps[-1].step_order if steps else "?"
    generation_mode = capabilities.final_output_generation_mode
    generation_label = (
        {
            "template_fill": "mall",
            "generated": "genererad",
        }.get(generation_mode)
        if generation_mode is not None
        else None
    )
    base = f"{_format_output_label(capabilities.final_output_mode)} via steg {final_step_order}"
    return f"{base} ({generation_label})" if generation_label else base


def _form_field_names(flow: Flow) -> list[str]:
    metadata_json = flow.metadata_json
    if not isinstance(metadata_json, dict):
        return []
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return []
    fields = cast(JsonObject, form_schema).get("fields")
    if not isinstance(fields, list):
        return []
    return [
        str(cast(JsonObject, field).get("name")).strip()
        for field in cast(list[object], fields)
        if isinstance(field, dict)
        and str(cast(JsonObject, field).get("name", "")).strip()
    ]


def _knowledge_base_summary(
    steps: list[FlowStep],
    assistant_snapshots: AssistantAuthoringSnapshots | None,
) -> str | None:
    if not assistant_snapshots:
        return None
    parts: list[str] = []
    for step in steps:
        snapshot = assistant_snapshots.get(step.assistant_id)
        if snapshot is None:
            continue
        display_values = _display_snapshot_resources(snapshot.knowledge_refs)
        if display_values:
            parts.append(f"steg {step.step_order} ({', '.join(display_values)})")
    return "; ".join(parts) or None


def _display_snapshot_resources(
    refs: tuple[AssistantAuthoringResourceRef, ...],
) -> list[str]:
    return [resource.display_value for resource in refs]


def _format_step_ranges(step_orders: tuple[int, ...]) -> str | None:
    if not step_orders:
        return None
    sorted_orders = sorted(step_orders)
    ranges: list[str] = []
    start = end = sorted_orders[0]
    for order in sorted_orders[1:]:
        if order == end + 1:
            end = order
            continue
        ranges.append(_format_step_range(start, end))
        start = end = order
    ranges.append(_format_step_range(start, end))
    return ", ".join(ranges)


def _format_step_range(start: int, end: int) -> str:
    if start == end:
        return f"steg {start}"
    return f"steg {start}–{end}"


def _format_active_families(edit_scope: "EditScopeResolution") -> str:
    families = sorted(edit_scope.active_families)
    if not families:
        return "okänt"
    return ", ".join(families)


def _format_requested_output_change(
    *,
    capabilities: FlowCapabilityProfile,
    edit_scope: "EditScopeResolution",
) -> str | None:
    requested = edit_scope.requested_output_artifact
    current = capabilities.final_output_mode
    if requested is None or requested == current:
        return None
    return f"{_format_output_label(current)} -> {_format_output_label(requested)}"


def _format_unresolved_output_decision(
    edit_scope: "EditScopeResolution",
) -> str | None:
    if (
        edit_scope.requested_output_artifact == "docx_document"
        and edit_scope.requested_output_generation_mode is None
    ):
        return "DOCX-generering (genererad eller mall)"
    if (
        edit_scope.requested_output_artifact == "pdf_document"
        and edit_scope.requested_output_generation_mode == "pdf_template_requested"
    ):
        return "PDF-generering (genererad PDF eller mallförväntan)"
    return None


def _format_output_label(output_mode: str | None) -> str:
    return {
        "structured_text": "Text",
        "structured_json": "JSON",
        "pdf_document": "PDF",
        "docx_document": "DOCX",
        None: "(okänd)",
    }.get(output_mode, str(output_mode))


def _build_step_synopsis(instructions: str) -> str:
    """Build a safe synopsis from raw assistant instructions.

    Extracts the first sentence or line as a purpose summary, avoiding
    injecting the full untrusted instructions into the system prompt.
    """
    for line in instructions.split("\n"):
        stripped = line.strip()
        if stripped:
            for end in (".", "!", "。"):
                idx = stripped.find(end)
                if 0 < idx < 120:
                    return stripped[: idx + 1]
            return stripped[:120] + ("..." if len(stripped) > 120 else "")
    return "(no instructions)"
