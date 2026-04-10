from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import get_close_matches
from typing import Any, cast

from intric.flows.domain.flow import FlowStepResult, JsonObject
from intric.flows.flow_variable_definitions import RESERVED_RUNTIME_VARIABLES_NORMALIZED
from intric.main.exceptions import BadRequestException

_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+)\s*\}\}")
_STEP_ALIAS_PATTERN = re.compile(r"^step_\d+($|[._])")


def iter_template_expressions(template: str) -> list[str]:
    """Extract templated variable expressions from a template string."""
    return [
        match.group(1).strip() for match in _TEMPLATE_VAR_PATTERN.finditer(template)
    ]


class FlowVariableResolver:
    """Resolves flow template variables from run input and prior step outputs."""

    def build_context(
        self,
        flow_input: dict[str, Any] | None,
        prior_results: list[FlowStepResult],
        *,
        current_step_order: int | None = None,
        step_names_by_order: dict[int, str] | None = None,
        current_step_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_flow_input = flow_input or {}
        context: dict[str, Any] = {
            "flow_input": normalized_flow_input,
            "flow": {"input": normalized_flow_input},
            "datum": datetime.now().date().isoformat(),
        }

        # Friendly input field aliases (for example {{Namn på brukare}})
        for key, value in normalized_flow_input.items():
            normalized_key = key.strip()
            if not normalized_key:
                continue
            if normalized_key in context:
                continue
            if normalized_key.casefold() in RESERVED_RUNTIME_VARIABLES_NORMALIZED:
                continue
            if _STEP_ALIAS_PATTERN.match(normalized_key.casefold()):
                continue
            if "." in normalized_key:
                continue
            context[normalized_key] = value

        # System aliases from available runtime input payload
        transcript_value = self._extract_transcript_value(normalized_flow_input)
        if transcript_value is not None:
            context["transkribering"] = transcript_value

        text_value = normalized_flow_input.get("text")
        if isinstance(text_value, str) and text_value.strip():
            context["indata_text"] = text_value

        json_value = normalized_flow_input.get("json")
        if json_value is None:
            json_value = normalized_flow_input.get("structured")
        if isinstance(json_value, (dict, list)):
            context["indata_json"] = json_value

        file_ids_value = normalized_flow_input.get("file_ids")
        if isinstance(file_ids_value, list):
            context["indata_filer"] = file_ids_value

        for result in prior_results:
            runtime_input = self._extract_runtime_input(result)
            step_ctx = {
                "input": runtime_input,
                "output": result.output_payload_json or {},
                "status": result.status.value,
                "error_message": result.error_message,
            }
            # CRITICAL: Variable keys use step_order for human-readable prompts (e.g., {{step_1.output}}).
            # Execution identity (hashing, DB uniqueness) strictly uses step_id.
            context[f"step_{result.step_order}"] = step_ctx

        if current_step_order is not None and current_step_order > 1:
            previous_result = next(
                (
                    item
                    for item in prior_results
                    if item.step_order == current_step_order - 1
                ),
                None,
            )
            if previous_result is not None:
                context["föregående_steg"] = self._extract_step_text(previous_result)

        if step_names_by_order:
            for result in prior_results:
                step_name = step_names_by_order.get(result.step_order, "").strip()
                if not step_name:
                    continue
                if step_name in context:
                    continue
                context[step_name] = self._extract_step_text(result)

        if isinstance(current_step_input, dict):
            context["step_input"] = current_step_input
            if current_step_order is not None:
                step_key = f"step_{current_step_order}"
                existing = context.get(step_key)
                if isinstance(existing, dict):
                    existing["input"] = current_step_input
                else:
                    context[step_key] = {"input": current_step_input}

        return context

    def interpolate(self, template: str, context: dict[str, Any]) -> str:
        def _replace(match: re.Match[str]) -> str:
            var_path = match.group(1).strip()
            value = self._resolve_path(context, var_path)
            return self._to_prompt_string(value)

        return _TEMPLATE_VAR_PATTERN.sub(_replace, template)

    def resolve_path(self, context: dict[str, Any], path: str) -> Any:
        return self._resolve_path(context, path)

    def _resolve_path(self, context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for token in path.split("."):
            token = token.strip()
            if not token:
                raise BadRequestException(
                    f"Unknown variable reference: '{path}'. Empty path segment is not allowed."
                )
            if isinstance(current, dict):
                current_dict = cast(JsonObject, current)
                if token not in current_dict:
                    available_keys = [str(key) for key in current_dict.keys()]
                    suggestion = _format_missing_key_suggestion(
                        token=token, available_keys=available_keys
                    )
                    raise BadRequestException(
                        f"Unknown variable reference: '{path}'. Missing key '{token}'.{suggestion}"
                    )
                current = current_dict[token]
                continue

            if isinstance(current, list):
                current_list = cast(list[Any], current)
                if not token.isdigit():
                    raise BadRequestException(
                        f"Unknown variable reference: '{path}'. "
                        f"Expected numeric index for list access, got '{token}'."
                    )
                index = int(token)
                if index >= len(current_list):
                    raise BadRequestException(
                        f"Unknown variable reference: '{path}'. "
                        f"List index '{index}' is out of range."
                    )
                current = current_list[index]
                continue

            raise BadRequestException(
                f"Unknown variable reference: '{path}'. "
                f"Cannot access '{token}' on value type '{type(current).__name__}'."
            )

        return current

    def _to_prompt_string(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            value_list = cast(list[Any], value)
            if len(value_list) <= 10 and all(
                _is_prompt_scalar(item) for item in value_list
            ):
                return ", ".join(_scalar_to_prompt_string(item) for item in value_list)
        if isinstance(value, dict):
            value_dict = cast(JsonObject, value)
            if value_dict and all(
                _is_prompt_scalar(item) for item in value_dict.values()
            ):
                return "\n".join(
                    f"{key}: {_scalar_to_prompt_string(item)}"
                    for key, item in value_dict.items()
                )
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    @staticmethod
    def _extract_step_text(result: FlowStepResult) -> str:
        payload = result.output_payload_json or {}
        text = payload.get("text")
        if isinstance(text, str):
            return text
        if isinstance(text, (dict, list)):
            return json.dumps(text, ensure_ascii=False)
        if text is not None:
            return str(text)
        structured = payload.get("structured")
        if isinstance(structured, (dict, list)):
            return json.dumps(structured, ensure_ascii=False)
        if structured is not None:
            return str(structured)
        return ""

    @staticmethod
    def _extract_transcript_value(flow_input: dict[str, Any]) -> str | None:
        for key in (
            "transkribering",
            "transcription",
            "transcript",
            "transcribed_text",
        ):
            value = flow_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def _extract_runtime_input(result: FlowStepResult) -> dict[str, Any]:
        payload = result.input_payload_json or {}
        runtime_input = payload.get("runtime_input")
        if isinstance(runtime_input, dict):
            return dict(cast(JsonObject, runtime_input))
        return {}


def _is_prompt_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_to_prompt_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_missing_key_suggestion(*, token: str, available_keys: list[str]) -> str:
    if not available_keys:
        return ""
    if len(available_keys) <= 8:
        return f" Available keys: {', '.join(sorted(available_keys))}."
    matches = get_close_matches(token, available_keys, n=3, cutoff=0.6)
    if matches:
        return f" Did you mean: {', '.join(matches)}?"
    return ""
