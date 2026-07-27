from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Literal, cast
from uuid import UUID

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStepResult
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputJsonPath,
    FlowResolvedInputRuntimeSource,
    FlowResolvedInputSource,
    FlowResolvedInputStepResultSource,
    FlowResolvedInputSystemValueSource,
    build_resolved_input_edge,
    merge_resolved_input_edges,
)
from eneo.flows.flow_variable_definitions import can_expose_form_field_bare_alias
from eneo.main.exceptions import TypedIOValidationException

_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+)\s*\}\}")


def _variable_resolution_error(message: str) -> TypedIOValidationException:
    return TypedIOValidationException(
        message,
        code=FlowApiErrorCode.TYPED_IO_VARIABLE_RESOLUTION_FAILED.value,
    )


@dataclass(frozen=True, slots=True)
class _UnavailableStepText:
    message: str
    code: FlowApiErrorCode


_ResolvedPathSegment = str | int
_VariableSourceKind = Literal[
    "flow_input", "step_result", "system_value", "runtime_input"
]


@dataclass(frozen=True, slots=True)
class _VariableSourceDescriptor:
    kind: _VariableSourceKind
    selector_prefix: tuple[_ResolvedPathSegment, ...] = ()
    source_step_id: UUID | None = None
    source_attempt_no: int | None = None
    system_name: str | None = None


class FlowVariableContext(dict[str, Any]):
    __slots__ = ("_source_descriptors",)

    def __init__(self) -> None:
        super().__init__()
        self._source_descriptors: dict[
            tuple[_ResolvedPathSegment, ...], _VariableSourceDescriptor
        ] = {}

    def register_source(
        self,
        context_path: tuple[_ResolvedPathSegment, ...],
        descriptor: _VariableSourceDescriptor,
    ) -> None:
        self._source_descriptors[context_path] = descriptor

    def source_for_path(
        self,
        resolved_path: tuple[_ResolvedPathSegment, ...],
    ) -> tuple[_VariableSourceDescriptor, tuple[_ResolvedPathSegment, ...]] | None:
        matches = [
            (context_path, descriptor)
            for context_path, descriptor in self._source_descriptors.items()
            if resolved_path[: len(context_path)] == context_path
        ]
        if not matches:
            return None
        context_path, descriptor = max(matches, key=lambda match: len(match[0]))
        return descriptor, resolved_path[len(context_path) :]


@dataclass(frozen=True, slots=True)
class FlowVariableInterpolation:
    text: str
    edges: tuple[FlowResolvedInputEdge, ...]


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
        step_ref_mapping: dict[str, int] | None = None,
        current_step_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return dict(
            self.build_context_with_evidence(
                flow_input,
                prior_results,
                current_step_order=current_step_order,
                step_names_by_order=step_names_by_order,
                step_ref_mapping=step_ref_mapping,
                current_step_input=current_step_input,
            )
        )

    def build_context_with_evidence(
        self,
        flow_input: dict[str, Any] | None,
        prior_results: list[FlowStepResult],
        *,
        current_step_order: int | None = None,
        step_names_by_order: dict[int, str] | None = None,
        step_ref_mapping: dict[str, int] | None = None,
        current_step_input: dict[str, Any] | None = None,
    ) -> FlowVariableContext:
        normalized_flow_input = flow_input or {}
        context = FlowVariableContext()
        context.update(
            {
                "flow_input": normalized_flow_input,
                "flow": {"input": normalized_flow_input},
                "datum": datetime.now().date().isoformat(),
            }
        )
        flow_input_source = _VariableSourceDescriptor(kind="flow_input")
        context.register_source(("flow_input",), flow_input_source)
        context.register_source(("flow", "input"), flow_input_source)
        context.register_source(
            ("datum",),
            _VariableSourceDescriptor(kind="system_value", system_name="datum"),
        )

        # Friendly input field aliases (for example {{Namn på brukare}})
        for key, value in normalized_flow_input.items():
            normalized_key = key.strip()
            if not normalized_key:
                continue
            if normalized_key in context:
                continue
            if not can_expose_form_field_bare_alias(normalized_key):
                continue
            context[normalized_key] = value
            context.register_source(
                (normalized_key,),
                _VariableSourceDescriptor(
                    kind="flow_input", selector_prefix=(normalized_key,)
                ),
            )

        transcript_source = self._extract_transcript_source(normalized_flow_input)
        if transcript_source is not None:
            transcript_key, transcript_value = transcript_source
            context[FLOW_INPUT_TRANSCRIPTION_KEY] = transcript_value
            context.register_source(
                (FLOW_INPUT_TRANSCRIPTION_KEY,),
                _VariableSourceDescriptor(
                    kind="flow_input", selector_prefix=(transcript_key,)
                ),
            )

        text_value = normalized_flow_input.get("text")
        if isinstance(text_value, str) and text_value.strip():
            context["indata_text"] = text_value
            context.register_source(
                ("indata_text",),
                _VariableSourceDescriptor(kind="flow_input", selector_prefix=("text",)),
            )

        json_value = normalized_flow_input.get("json")
        json_source_key = "json"
        if json_value is None:
            json_value = normalized_flow_input.get("structured")
            json_source_key = "structured"
        if isinstance(json_value, (dict, list)):
            context["indata_json"] = json_value
            context.register_source(
                ("indata_json",),
                _VariableSourceDescriptor(
                    kind="flow_input", selector_prefix=(json_source_key,)
                ),
            )

        step_text_by_order: dict[int, str | _UnavailableStepText] = {}
        for result in prior_results:
            runtime_input = self._extract_runtime_input(result)
            output = dict(result.output_payload_json or {})
            step_text = self._extract_step_text(result)
            step_text_by_order[result.step_order] = step_text
            if "text" in output or OUTPUT_TEXT_OVERFLOW_KEY in output:
                output.pop(OUTPUT_TEXT_OVERFLOW_KEY, None)
                output["text"] = step_text
            step_ctx = {
                "input": runtime_input,
                "output": output,
                "status": result.status.value,
                "error_message": result.error_message,
            }
            # Prompt aliases follow authored order; persisted execution identity uses step_id.
            step_key = f"step_{result.step_order}"
            context[step_key] = step_ctx
            context.register_source(
                (step_key,),
                _VariableSourceDescriptor(
                    kind="step_result",
                    source_step_id=result.step_id,
                    source_attempt_no=result.current_attempt_no,
                ),
            )

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
                context["föregående_steg"] = step_text_by_order[
                    previous_result.step_order
                ]
                context.register_source(
                    ("föregående_steg",),
                    _VariableSourceDescriptor(
                        kind="step_result",
                        selector_prefix=("output", "text"),
                        source_step_id=previous_result.step_id,
                        source_attempt_no=previous_result.current_attempt_no,
                    ),
                )

        if step_names_by_order:
            for result in prior_results:
                step_name = step_names_by_order.get(result.step_order, "").strip()
                if not step_name:
                    continue
                if (
                    step_ref_mapping is None
                    or step_ref_mapping.get(step_name) != result.step_order
                ):
                    continue
                if step_name in context:
                    continue
                context[step_name] = step_text_by_order[result.step_order]
                context.register_source(
                    (step_name,),
                    _VariableSourceDescriptor(
                        kind="step_result",
                        selector_prefix=("output", "text"),
                        source_step_id=result.step_id,
                        source_attempt_no=result.current_attempt_no,
                    ),
                )

        if isinstance(current_step_input, dict):
            context["step_input"] = current_step_input
            runtime_source = _VariableSourceDescriptor(kind="runtime_input")
            context.register_source(("step_input",), runtime_source)
            if current_step_order is not None:
                step_key = f"step_{current_step_order}"
                existing = context.get(step_key)
                if isinstance(existing, dict):
                    existing["input"] = current_step_input
                else:
                    context[step_key] = {"input": current_step_input}
                context.register_source((step_key, "input"), runtime_source)

        return context

    def interpolate(self, template: str, context: dict[str, Any]) -> str:
        def _replace(match: re.Match[str]) -> str:
            var_path = match.group(1).strip()
            value = self._resolve_path(context, var_path)
            return self._to_prompt_string(value)

        return _TEMPLATE_VAR_PATTERN.sub(_replace, template)

    def interpolate_with_evidence(
        self,
        template: str,
        context: FlowVariableContext,
        *,
        binding_ref: str,
    ) -> FlowVariableInterpolation:
        edges: list[FlowResolvedInputEdge] = []

        def _replace(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            value, resolved_path = self._resolve_path_with_segments(context, expression)
            source_match = context.source_for_path(resolved_path)
            if source_match is None:
                raise TypedIOValidationException(
                    f"Resolved variable reference '{expression}' has no evidence source.",
                    code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
                )
            descriptor, selector_tail = source_match
            edges.append(
                build_resolved_input_edge(
                    binding_ref=f"{binding_ref}:{expression}",
                    source=self._resolved_input_source(
                        descriptor,
                        selector_path=descriptor.selector_prefix + selector_tail,
                    ),
                    selected_value=value,
                )
            )
            return self._to_prompt_string(value)

        return FlowVariableInterpolation(
            text=_TEMPLATE_VAR_PATTERN.sub(_replace, template),
            edges=merge_resolved_input_edges(edges),
        )

    def resolve_path(self, context: dict[str, Any], path: str) -> Any:
        return self._resolve_path(context, path)

    def _resolve_path(self, context: dict[str, Any], path: str) -> Any:
        value, _ = self._resolve_path_with_segments(context, path)
        return value

    def _resolve_path_with_segments(
        self, context: dict[str, Any], path: str
    ) -> tuple[Any, tuple[_ResolvedPathSegment, ...]]:
        current: Any = context
        resolved_path: list[_ResolvedPathSegment] = []
        for token in path.split("."):
            token = token.strip()
            if not token:
                raise _variable_resolution_error(
                    f"Unknown variable reference: '{path}'. Empty path segment is not allowed."
                )
            if isinstance(current, dict):
                current_dict = cast(FlowPersistedJsonObject, current)
                if token not in current_dict:
                    available_keys = [str(key) for key in current_dict.keys()]
                    suggestion = _format_missing_key_suggestion(
                        token=token, available_keys=available_keys
                    )
                    raise _variable_resolution_error(
                        f"Unknown variable reference: '{path}'. Missing key '{token}'.{suggestion}"
                    )
                current = current_dict[token]
                resolved_path.append(token)
                continue

            if isinstance(current, list):
                current_list = cast(list[Any], current)
                if not token.isdigit():
                    raise _variable_resolution_error(
                        f"Unknown variable reference: '{path}'. "
                        f"Expected numeric index for list access, got '{token}'."
                    )
                index = int(token)
                if index >= len(current_list):
                    raise _variable_resolution_error(
                        f"Unknown variable reference: '{path}'. "
                        f"List index '{index}' is out of range."
                    )
                current = current_list[index]
                resolved_path.append(index)
                continue

            if isinstance(current, _UnavailableStepText):
                self._raise_if_step_text_unavailable(current)
            raise _variable_resolution_error(
                f"Unknown variable reference: '{path}'. "
                f"Cannot access '{token}' on value type '{type(current).__name__}'."
            )

        self._raise_if_step_text_unavailable(current)
        return current, tuple(resolved_path)

    @staticmethod
    def _resolved_input_source(
        descriptor: _VariableSourceDescriptor,
        *,
        selector_path: tuple[_ResolvedPathSegment, ...],
    ) -> FlowResolvedInputSource:
        selector = FlowResolvedInputJsonPath(kind="json_path", path=selector_path)
        if descriptor.kind == "flow_input":
            return FlowResolvedInputFlowInputSource(
                kind="flow_input", selector=selector
            )
        if descriptor.kind == "runtime_input":
            return FlowResolvedInputRuntimeSource(
                kind="runtime_input", selector=selector
            )
        if descriptor.kind == "system_value":
            if descriptor.system_name is None or selector_path:
                raise TypedIOValidationException(
                    "System variable evidence source is invalid.",
                    code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
                )
            return FlowResolvedInputSystemValueSource(
                kind="system_value", name=descriptor.system_name
            )
        if descriptor.source_step_id is None or descriptor.source_attempt_no is None:
            raise TypedIOValidationException(
                "Consumed prior step result is missing its current attempt identity.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        return FlowResolvedInputStepResultSource(
            kind="step_result",
            source_step_id=descriptor.source_step_id,
            source_attempt_no=descriptor.source_attempt_no,
            selector=selector,
        )

    def _to_prompt_string(self, value: Any) -> str:
        self._raise_if_step_text_unavailable(value)
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
            value_dict = cast(FlowPersistedJsonObject, value)
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

    @classmethod
    def _raise_if_step_text_unavailable(cls, value: Any) -> None:
        if isinstance(value, _UnavailableStepText):
            raise TypedIOValidationException(
                value.message,
                code=value.code.value,
            )
        if isinstance(value, dict):
            for child in cast(dict[object, Any], value).values():
                cls._raise_if_step_text_unavailable(child)
        elif isinstance(value, list):
            for child in cast(list[Any], value):
                cls._raise_if_step_text_unavailable(child)

    @staticmethod
    def _extract_step_text(
        result: FlowStepResult,
    ) -> str | _UnavailableStepText:
        payload = result.output_payload_json or {}
        if "text" in payload or OUTPUT_TEXT_OVERFLOW_KEY in payload:
            try:
                text = interpret_step_text(payload)
            except StepOutputMetadataError:
                return _UnavailableStepText(
                    message=(
                        "Step text is unavailable to templates because it has "
                        "malformed persisted text metadata."
                    ),
                    code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION,
                )
            if isinstance(text, FileBackedStepText):
                return _UnavailableStepText(
                    message=(
                        "Complete step text is unavailable to templates because it "
                        "is stored in a generated output file."
                    ),
                    code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE,
                )
            return text.text
        structured = payload.get("structured")
        if isinstance(structured, (dict, list)):
            return json.dumps(structured, ensure_ascii=False)
        if structured is not None:
            return str(structured)
        return ""

    @staticmethod
    def _extract_transcript_source(
        flow_input: dict[str, Any],
    ) -> tuple[str, str] | None:
        for key in (
            FLOW_INPUT_TRANSCRIPTION_KEY,
            "transcription",
            "transcript",
            "transcribed_text",
        ):
            value = flow_input.get(key)
            if isinstance(value, str) and value.strip():
                return key, value
        return None

    @staticmethod
    def _extract_runtime_input(result: FlowStepResult) -> dict[str, Any]:
        payload = result.input_payload_json or {}
        runtime_input = payload.get("runtime_input")
        if isinstance(runtime_input, dict):
            return dict(cast(FlowPersistedJsonObject, runtime_input))
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
