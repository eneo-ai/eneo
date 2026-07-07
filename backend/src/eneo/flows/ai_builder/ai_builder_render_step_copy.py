from __future__ import annotations

from eneo.flows.flow_authoring_spec import OutputType


def render_step_display_copy(
    output_type: OutputType,
    *,
    ui_language: str | None,
) -> str:
    output_label = output_type.value.upper()
    if ui_language == "sv":
        return f"Rendera {output_label}"
    return f"Render {output_label}"
