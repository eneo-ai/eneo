from __future__ import annotations

from eneo.flows.flow_authoring_spec import OutputType


def render_step_display_copy(
    output_type: OutputType,
    *,
    ui_language: str | None,
) -> str:
    output_label = output_type.value.upper()
    if ui_language is not None and ui_language.casefold().startswith("en"):
        return f"Render {output_label}"
    return f"Rendera {output_label}"
