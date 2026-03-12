from typing import Any, Optional

from pydantic import BaseModel

from intric.main.models import GeneralError


def streaming_response(
    model: Optional[BaseModel] = None,
    response_codes: list[int] = None,
    models: list[BaseModel] = None,
) -> dict[int | str, Any]:
    """Define a streaming response with Server-Sent Events.

    Args:
        model: (Deprecated) The main response model (kept for backwards compatibility)
        response_codes: List of error response codes
        models: List of models that can be returned in the stream
    """
    # Initialize schema
    schema: dict[str, Any] = {}

    # Handle different input formats for backward compatibility
    if models:
        # If models is provided, use it directly
        schema["oneOf"] = [
            model.model_json_schema(ref_template="#/components/schemas/{model}")
            for model in models
        ]
    elif model:
        # If only model is provided (backwards compatibility)
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")

    streaming: dict[int | str, Any] = {200: {"content": {"text/event-stream": {"schema": schema}}}}

    if response_codes is not None:
        codes = get_responses(response_codes)
        streaming.update(codes)

    return streaming


def get_responses(response_codes: list[int]) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": GeneralError} for code in response_codes}
