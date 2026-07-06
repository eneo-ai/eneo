from __future__ import annotations

ALLOWED_OUTPUT_MODES = {
    "pass_through",
    "http_post",
    "transcribe_only",
    "template_fill",
    "render_verbatim",
}


def transcribe_only_violation(
    *,
    step_order: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> str | None:
    if output_mode != "transcribe_only":
        return None
    if input_type != "audio":
        return f"Step {step_order}: output_mode 'transcribe_only' requires input_type 'audio'."
    if output_type != "text":
        return f"Step {step_order}: output_mode 'transcribe_only' requires output_type 'text'."
    return None


def render_verbatim_violation(
    *,
    step_order: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> str | None:
    if output_mode != "render_verbatim":
        return None
    if input_type != "text":
        return f"Step {step_order}: output_mode 'render_verbatim' requires input_type 'text'."
    if output_type not in {"pdf", "docx"}:
        return (
            f"Step {step_order}: output_mode 'render_verbatim' requires output_type "
            "'pdf' or 'docx'."
        )
    return None
