from __future__ import annotations

import json
import re
from typing import Any

from intric.flows.flow import FlowStepResult
from intric.main.exceptions import BadRequestException


_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+)\s*\}\}")


def iter_template_expressions(template: str) -> list[str]:
    """Extract templated variable expressions from a template string."""
    return [match.group(1).strip() for match in _TEMPLATE_VAR_PATTERN.finditer(template)]


class FlowVariableResolver:
    """Resolves flow template variables from run input and prior step outputs."""

    def build_context(
        self,
        flow_input: dict[str, Any] | None,
        prior_results: list[FlowStepResult],
    ) -> dict[str, Any]:
        normalized_flow_input = flow_input or {}
        context: dict[str, Any] = {
            "flow_input": normalized_flow_input,
            "flow": {"input": normalized_flow_input},
        }

        for result in prior_results:
            step_ctx = {
                "output": result.output_payload_json or {},
                "status": result.status.value,
                "error_message": result.error_message,
            }
            # CRITICAL: Variable keys use step_order for human-readable prompts (e.g., {{step_1.output}}).
            # Execution identity (hashing, DB uniqueness) strictly uses step_id.
            context[f"step_{result.step_order}"] = step_ctx

        return context

    def interpolate(self, template: str, context: dict[str, Any]) -> str:
        def _replace(match: re.Match[str]) -> str:
            var_path = match.group(1).strip()
            value = self._resolve_path(context, var_path)
            return self._to_prompt_string(value)

        return _TEMPLATE_VAR_PATTERN.sub(_replace, template)

    def _resolve_path(self, context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for token in path.split("."):
            if isinstance(current, dict):
                if token not in current:
                    raise BadRequestException(
                        f"Unknown variable reference: '{path}'. Missing key '{token}'."
                    )
                current = current[token]
                continue

            if isinstance(current, list):
                if not token.isdigit():
                    raise BadRequestException(
                        f"Unknown variable reference: '{path}'. "
                        f"Expected numeric index for list access, got '{token}'."
                    )
                index = int(token)
                if index >= len(current):
                    raise BadRequestException(
                        f"Unknown variable reference: '{path}'. "
                        f"List index '{index}' is out of range."
                    )
                current = current[index]
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
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
