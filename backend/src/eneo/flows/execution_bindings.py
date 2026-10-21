"""Pin execution dependencies without introducing another runtime model."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from eneo.flows.definition import (
    DocumentStep,
    FlowDefinition,
    FunctionStep,
    LlmStep,
    TranscribeStep,
)
from eneo.flows.flow_functions import flows_assistant_id
from eneo.flows.schema_validation import check_schema
from eneo.main.exceptions import BadRequestException


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def model_binding(model: Any) -> dict[str, Any]:
    return {
        "model_id": str(model.id),
        "fingerprint": fingerprint(
            {
                name: getattr(model, name, None)
                for name in (
                    "id",
                    "name",
                    "provider_id",
                    "provider_type",
                    "base_url",
                    "deployment_name",
                    "litellm_model_name",
                    "max_input_tokens",
                    "max_output_tokens",
                )
            }
        ),
    }


async def bind_execution(
    definition: FlowDefinition,
    space: Any,
    assistant_service: Any,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve once at publication; later resolve pinned models and detect drift."""
    steps: dict[str, Any] = {}
    for step in definition.steps:
        prior = (expected or {}).get("steps", {}).get(step.key, {})
        model = None
        if isinstance(step, LlmStep):
            model_id = step.model_id or prior.get("model_id")
            model = (
                space.get_completion_model(UUID(str(model_id)))
                if model_id
                else space.get_default_completion_model()
            )
        elif isinstance(step, TranscribeStep):
            model_id = step.transcription_model_id or prior.get("model_id")
            model = (
                space.get_transcription_model(UUID(str(model_id)))
                if model_id
                else space.get_default_transcription_model()
            )
        if isinstance(step, (LlmStep, TranscribeStep)):
            if model is None or not model.can_access:
                raise BadRequestException(
                    f"Step '{step.key}' needs an available model. Republish after reviewing its configuration."
                )
            space.validate_model_security_compatibility(model)
            steps[step.key] = model_binding(model)
            if isinstance(step, TranscribeStep) and step.speaker_mapping:
                mapping_id = step.speaker_mapping.model_id or prior.get(
                    "speaker_model", {}
                ).get("model_id")
                mapping_model = (
                    space.get_completion_model(UUID(str(mapping_id)))
                    if mapping_id
                    else space.get_default_completion_model()
                )
                if mapping_model is None or not mapping_model.can_access:
                    raise BadRequestException(
                        f"Step '{step.key}' needs an available speaker-naming model."
                    )
                space.validate_model_security_compatibility(mapping_model)
                steps[step.key]["speaker_model"] = model_binding(mapping_model)
        if isinstance(step, (FunctionStep, DocumentStep)):
            purpose = (
                step.purpose if isinstance(step, FunctionStep) else "file_creation"
            )
            assistant_id = flows_assistant_id(space)
            server = (
                await assistant_service.capability_server(
                    assistant_id=assistant_id, purpose=purpose
                )
                if assistant_id
                else None
            )
            if server is None:
                raise BadRequestException(
                    f"Step '{step.key}' needs an available {purpose} provider before publication."
                )
            if isinstance(step, FunctionStep):
                tool = next(
                    (tool for tool in server.tools if tool.name == step.tool), None
                )
                if tool is None:
                    raise BadRequestException(
                        f"Step '{step.key}' names a tool the provider no longer offers."
                    )
                schema = dict(tool.input_schema or {})
                try:
                    check_schema(schema, authored=False)
                except ValueError as exc:
                    raise BadRequestException(
                        f"Step '{step.key}' has an unsafe tool schema: {exc}"
                    ) from exc
                tool_fingerprint = fingerprint(schema)
            else:
                tool_fingerprint = fingerprint(
                    sorted((tool.name, tool.input_schema) for tool in server.tools)
                )
            steps[step.key] = {
                "provider_id": str(server.id),
                "fingerprint": fingerprint(
                    {
                        "schema": tool_fingerprint,
                        "http_url": getattr(server, "http_url", None),
                    }
                ),
            }
    result = {"version": 1, "steps": steps}
    if expected is not None and result != expected:
        raise BadRequestException(
            "A published model or function changed. Review the flow and republish before running it."
        )
    return result
