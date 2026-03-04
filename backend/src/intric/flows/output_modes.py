from __future__ import annotations

ALLOWED_OUTPUT_MODES = {"pass_through", "http_post", "transcribe_only"}


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
        return (
            f"Step {step_order}: output_mode 'transcribe_only' requires input_type 'audio'."
        )
    if output_type != "text":
        return (
            f"Step {step_order}: output_mode 'transcribe_only' requires output_type 'text'."
        )
    return None
