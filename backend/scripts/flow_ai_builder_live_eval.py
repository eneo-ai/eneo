#!/usr/bin/env python3
"""Run the Flow AI Builder normal-user live eval against a local API.

This script is a small production-readiness diagnostic runner, not an
observability platform, persisted issue tracker, or arbitrary payload redactor.
It talks only through the public AI Builder API, reads secrets from environment
variables, and writes sanitized artifacts for the five-case output-quality gate.
"""

from __future__ import annotations

# Manual live-environment regression script. Do not auto-collect via pytest.
__test__ = False

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias, cast

import httpx

from intric.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
    analyze_template,
)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
TerminalOutput: TypeAlias = Literal[
    "structured_json",
    "structured_text",
    "docx_document",
    "pdf_document",
]
Verdict: TypeAlias = Literal["pass", "fail", "incomplete"]
QuestionBindingRole: TypeAlias = Literal["any", "writing_or_materialization"]

API_PREFIX = "/api/v1"
AI_BUILDER_PREFIX = f"{API_PREFIX}/flows/ai-builder"
DEFAULT_BASE_URL = "http://127.0.0.1:8123"
DEFAULT_OUTPUT_ROOT = Path("/tmp/flow-ai-builder-t026-live-eval")
DEFAULT_LEDGER_PATH = (
    Path(__file__).resolve().parents[2]
    / ".codex"
    / "artifacts"
    / "flow-ai-builder-live-eval.md"
)


@dataclass(frozen=True, slots=True)
class ExpectedQuestionBinding:
    step_role: QuestionBindingRole = "any"
    require_text_ref: bool = False
    require_structured_field_ref: bool = False
    forbid_broad_structured_ref: bool = False


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    terminal_output: TerminalOutput | None = None
    required_input_types: tuple[str, ...] = ()
    forbidden_input_types: tuple[str, ...] = ()
    required_form_fields: tuple[str, ...] = ()
    forbidden_output_types: tuple[str, ...] = ()
    required_input_summary_terms: tuple[str, ...] = ()
    forbidden_input_summary_terms: tuple[str, ...] = ()
    forbidden_output_summary_terms: tuple[str, ...] = ()
    allowed_question_ids_without_plan: tuple[str, ...] = ()
    expected_question_bindings: tuple[ExpectedQuestionBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class LiveEvalCase:
    case_id: str
    title: str
    prompt: str
    expected: ExpectedOutcome
    question_answers: dict[str, tuple[str, ...]] = field(default_factory=lambda: {})
    max_turns: int = 4


@dataclass(frozen=True, slots=True)
class StreamEvent:
    event: str
    data: JsonValue


@dataclass(slots=True)
class LiveEvalResult:
    case_id: str
    title: str
    verdict: Verdict
    reasons: list[str]
    session_id: str | None = None
    plan_id: str | None = None
    plan_status: str | None = None
    revised_plan_id: str | None = None
    revised_plan_status: str | None = None
    event_sequence: list[str] = field(default_factory=lambda: [])
    terminal_output: str | None = None
    input_types: list[str] = field(default_factory=lambda: [])
    form_fields: list[str] = field(default_factory=lambda: [])
    requirements_summary: JsonObject | None = None
    questions: list[JsonObject] = field(default_factory=lambda: [])
    raw_artifact_dir: str | None = None


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    base_url: str
    api_key: str
    space_id: str
    output_root: Path
    ledger_path: Path
    per_case_timeout_seconds: float
    max_stream_events: int
    inter_case_delay_seconds: float


class LiveEvalError(RuntimeError):
    pass


class AIBuilderClient:
    def __init__(self, config: RunnerConfig) -> None:
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            headers={
                "X-API-Key": config.api_key,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(config.per_case_timeout_seconds),
        )

    def close(self) -> None:
        self._client.close()

    @property
    def space_id(self) -> str:
        return self._config.space_id

    def get_json(self, path: str) -> JsonObject:
        response = self._client.get(path)
        return _response_json_object(response)

    def post_json(self, path: str, payload: JsonObject) -> JsonObject:
        response = self._client.post(path, json=payload)
        return _response_json_object(response)

    def create_session(self, *, force_new: bool = True) -> JsonObject:
        return self.post_json(
            f"{AI_BUILDER_PREFIX}/sessions",
            {
                "target_kind": "create",
                "space_id": self._config.space_id,
                "force_new": force_new,
            },
        )

    def cancel_session(self, session_id: str) -> JsonObject:
        return self.post_json(f"{AI_BUILDER_PREFIX}/sessions/{session_id}/cancel", {})

    def get_plan(self, plan_id: str) -> JsonObject:
        return self.get_json(f"{AI_BUILDER_PREFIX}/plans/{plan_id}")

    def revise_plan(self, plan_id: str) -> JsonObject:
        return self.post_json(
            f"{AI_BUILDER_PREFIX}/plans/{plan_id}/revise",
            {"type": "keep_current_description"},
        )

    def send_message(
        self,
        *,
        session_id: str,
        message: str,
        model_id: str,
        question_answer: JsonObject | None = None,
    ) -> list[StreamEvent]:
        payload: JsonObject = {
            "message": message,
            "model_id": model_id,
            "ui_language": "en",
        }
        if question_answer is not None:
            payload["question_answer"] = question_answer

        events: list[StreamEvent] = []
        started = time.monotonic()
        with self._client.stream(
            "POST",
            f"{AI_BUILDER_PREFIX}/sessions/{session_id}/messages",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            active_event: str | None = None
            active_data: list[str] = []
            for line in response.iter_lines():
                if time.monotonic() - started > self._config.per_case_timeout_seconds:
                    raise LiveEvalError("stream timeout reached")
                if line == "":
                    if active_event is not None:
                        event = _build_stream_event(active_event, active_data)
                        events.append(event)
                        active_event = None
                        active_data = []
                        if event.event == "done":
                            break
                        if len(events) >= self._config.max_stream_events:
                            raise LiveEvalError("stream event limit reached")
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    active_event = line.removeprefix("event:").strip()
                    continue
                if line.startswith("data:"):
                    active_data.append(line.removeprefix("data:").strip())
                    continue
        return events


def _response_json_object(response: httpx.Response) -> JsonObject:
    response.raise_for_status()
    value = cast(object, response.json())
    if not isinstance(value, dict):
        raise LiveEvalError(f"Expected JSON object from {response.url}")
    return cast(JsonObject, value)


def _build_stream_event(event: str, data_lines: list[str]) -> StreamEvent:
    raw_data = "\n".join(data_lines)
    if raw_data == "":
        return StreamEvent(event=event, data="")
    try:
        return StreamEvent(event=event, data=cast(JsonValue, json.loads(raw_data)))
    except json.JSONDecodeError:
        return StreamEvent(event=event, data=raw_data)


def _object(value: JsonValue | None) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _array(value: JsonValue | None) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def _string(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _text_blob(value: JsonValue | None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()


def _choose_model_id(models_payload: JsonObject) -> str:
    items = _array(models_payload.get("items"))
    accessible: list[JsonObject] = []
    for item in items:
        model = _object(item)
        if model.get("can_access") is False or model.get("is_deprecated") is True:
            continue
        model_id = _string(model.get("id"))
        if model_id is not None:
            accessible.append(model)
    if not accessible:
        raise LiveEvalError("No accessible completion model returned by local API.")
    # Prefer the API's first accessible model over the organization default.
    # Local org defaults can be cost-optimized and turn output-quality checks
    # into model-capability checks instead of AI Builder behavior checks.
    selected = accessible[0]
    selected_id = _string(selected.get("id"))
    if selected_id is None:
        raise LiveEvalError("Selected completion model is missing id.")
    return selected_id


def _model_name(models_payload: JsonObject, model_id: str) -> str | None:
    for item in _array(models_payload.get("items")):
        model = _object(item)
        if _string(model.get("id")) == model_id:
            return _string(model.get("name"))
    return None


def _plan_from_events(events: list[StreamEvent]) -> JsonObject | None:
    for event in reversed(events):
        if event.event == "plan":
            plan = _object(event.data)
            return plan or None
    return None


def _latest_requirements_summary(events: list[StreamEvent]) -> JsonObject | None:
    for event in reversed(events):
        if event.event == "requirements_summary":
            summary = _object(event.data)
            return summary or None
    return None


def _questions_from_events(events: list[StreamEvent]) -> list[JsonObject]:
    return [_object(event.data) for event in events if event.event == "question"]


def _latest_question(events: list[StreamEvent]) -> JsonObject | None:
    questions = _questions_from_events(events)
    return questions[-1] if questions else None


def _plan_id(plan: JsonObject | None) -> str | None:
    return None if plan is None else _string(plan.get("plan_id"))


def _plan_status(plan: JsonObject | None) -> str | None:
    return None if plan is None else _string(plan.get("status"))


def _spec(plan: JsonObject | None) -> JsonObject:
    proposal = _object(None if plan is None else plan.get("proposal"))
    return _object(proposal.get("spec"))


def _steps(plan: JsonObject | None) -> list[JsonObject]:
    return [_object(item) for item in _array(_spec(plan).get("steps"))]


def _terminal_output(plan: JsonObject | None) -> str | None:
    steps = _steps(plan)
    if not steps:
        return None
    output_type = _string(steps[-1].get("output_type"))
    if output_type == "json":
        return "structured_json"
    if output_type == "text":
        return "structured_text"
    if output_type == "docx":
        return "docx_document"
    if output_type == "pdf":
        return "pdf_document"
    return output_type


def _input_types(plan: JsonObject | None) -> list[str]:
    seen: list[str] = []
    for step in _steps(plan):
        input_type = _string(step.get("input_type"))
        if input_type is not None and input_type not in seen:
            seen.append(input_type)
    return seen


def _output_types(plan: JsonObject | None) -> list[str]:
    seen: list[str] = []
    for step in _steps(plan):
        output_type = _string(step.get("output_type"))
        if output_type is not None and output_type not in seen:
            seen.append(output_type)
    return seen


def _form_fields(plan: JsonObject | None) -> list[str]:
    fields: list[str] = []
    for field_data in _array(_spec(plan).get("form_fields")):
        field_name = _string(_object(field_data).get("name"))
        if field_name is not None:
            fields.append(field_name)
    return fields


def _step_ref_indexes(plan: JsonObject) -> dict[str, int]:
    refs: dict[str, int] = {}
    for index, step in enumerate(_steps(plan), start=1):
        plan_step_ref = _string(step.get("plan_step_ref"))
        if plan_step_ref is not None:
            refs[plan_step_ref] = index
    return refs


def _question_binding_text(step: JsonObject) -> str | None:
    input_bindings = _object(step.get("input_bindings"))
    return _string(input_bindings.get("question"))


def _question_binding_candidate_steps(
    plan: JsonObject,
    *,
    role: QuestionBindingRole,
) -> list[JsonObject]:
    steps = _steps(plan)
    if role == "any":
        return steps

    for step in reversed(steps):
        output_type = _string(step.get("output_type"))
        if output_type not in {"text", "docx", "pdf"}:
            continue
        if _question_binding_text(step) is None:
            continue
        return [step]
    return []


def _question_binding_references(
    *,
    step: JsonObject,
    step_refs: dict[str, int],
) -> list[TemplateReference]:
    question = _question_binding_text(step)
    if question is None:
        return []
    return analyze_template(
        question,
        step_refs=step_refs,
        form_field_names=set(),
    )


def _has_text_step_ref(references: list[TemplateReference]) -> bool:
    return any(
        reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
        and reference.tail == "output.text"
        for reference in references
    )


def _has_structured_field_ref(references: list[TemplateReference]) -> bool:
    return any(
        reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
        and reference.structured_path is not None
        and len(reference.structured_path) > 0
        for reference in references
    )


def _has_broad_structured_ref(references: list[TemplateReference]) -> bool:
    return any(
        reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
        and (reference.tail == "output.structured" or reference.structured_path == ())
        for reference in references
    )


def _question_binding_failures(
    *,
    plan: JsonObject,
    expected: ExpectedQuestionBinding,
) -> list[str]:
    step_refs = _step_ref_indexes(plan)
    candidate_references = [
        _question_binding_references(step=step, step_refs=step_refs)
        for step in _question_binding_candidate_steps(
            plan,
            role=expected.step_role,
        )
    ]
    candidate_references = [refs for refs in candidate_references if refs]
    if not candidate_references:
        return [
            "No input_bindings.question found on a step matching "
            f"{expected.step_role!r}."
        ]

    failures: list[str] = []
    if (expected.require_text_ref or expected.require_structured_field_ref) and not any(
        (not expected.require_text_ref or _has_text_step_ref(refs))
        and (
            not expected.require_structured_field_ref or _has_structured_field_ref(refs)
        )
        for refs in candidate_references
    ):
        required_labels: list[str] = []
        if expected.require_text_ref:
            required_labels.append("source text")
        if expected.require_structured_field_ref:
            required_labels.append("selected structured field")
        failures.append(
            f"Missing required {' and '.join(required_labels)} refs in "
            f"{expected.step_role!r} question binding."
        )
    if expected.forbid_broad_structured_ref and any(
        _has_broad_structured_ref(refs) for refs in candidate_references
    ):
        failures.append(
            f"Observed broad structured JSON reference in {expected.step_role!r} "
            "question binding."
        )
    return failures


def _requirements_confirm_answer(summary: JsonObject) -> JsonObject:
    answer: JsonObject = {
        "kind": "requirements_confirmation",
        "requirements_confirmed": True,
    }
    version = _string(summary.get("requirements_version"))
    if version:
        answer["requirements_version"] = version
    return answer


def _question_answer_payload(
    question: JsonObject,
    desired_values: tuple[str, ...],
) -> tuple[str, JsonObject] | None:
    question_id = _string(question.get("question_id"))
    if question_id is None:
        return None

    selected_options: list[JsonObject] = []
    for option_data in _array(question.get("options")):
        option = _object(option_data)
        option_id = _string(option.get("id"))
        option_value = _string(option.get("value"))
        option_label = _string(option.get("label")) or ""
        if (
            (option_id is not None and option_id in desired_values)
            or (option_value is not None and option_value in desired_values)
            or option_label.casefold() in desired_values
        ):
            selected_options.append(option)

    if not selected_options:
        return None

    selected_labels = [
        _string(option.get("label")) or _string(option.get("id")) or "selected"
        for option in selected_options
    ]
    selected_option_ids = [
        option_id
        for option in selected_options
        if (option_id := _string(option.get("id"))) is not None
    ]
    selected_values = [
        option_value
        for option in selected_options
        if (option_value := _string(option.get("value"))) is not None
    ]
    payload: JsonObject = {
        "kind": "structured_question_answer",
        "question_id": question_id,
        "selected_option_ids": cast(JsonValue, selected_option_ids),
        "selected_values": cast(JsonValue, selected_values),
    }
    return ", ".join(selected_labels), payload


def _evaluate_plan_case(
    case: LiveEvalCase,
    *,
    plan: JsonObject | None,
    events: list[StreamEvent],
    requirements_summary: JsonObject | None,
) -> tuple[Verdict, list[str], str | None, list[str], list[str]]:
    expected = case.expected
    reasons: list[str] = []
    terminal = _terminal_output(plan)
    input_types = _input_types(plan)
    output_types = _output_types(plan)
    form_fields = _form_fields(plan)
    questions = _questions_from_events(events)

    if plan is None:
        allowed_question_ids = set(expected.allowed_question_ids_without_plan)
        if questions and allowed_question_ids:
            question_id = _string(questions[-1].get("question_id"))
            if question_id in allowed_question_ids:
                return (
                    "pass",
                    [f"Asked useful follow-up question {question_id}."],
                    (None),
                    input_types,
                    form_fields,
                )
        errors = [event for event in events if event.event == "error"]
        if errors:
            reasons.append(
                f"Stream returned error event: {_text_blob(errors[-1].data)}"
            )
            return "fail", reasons, terminal, input_types, form_fields
        return (
            "incomplete",
            ["No plan or accepted follow-up question produced."],
            (terminal),
            input_types,
            form_fields,
        )

    if expected.terminal_output is not None and terminal != expected.terminal_output:
        reasons.append(
            f"Expected terminal output {expected.terminal_output}, observed {terminal}."
        )

    for required in expected.required_input_types:
        if required not in input_types:
            reasons.append(f"Missing required input type {required}.")
    for forbidden in expected.forbidden_input_types:
        if forbidden in input_types:
            reasons.append(f"Observed forbidden input type {forbidden}.")
    for required in expected.required_form_fields:
        if required not in form_fields:
            reasons.append(f"Missing required form field {required}.")
    for forbidden in expected.forbidden_output_types:
        if forbidden in output_types:
            reasons.append(f"Observed forbidden output type {forbidden}.")

    input_description = ""
    output_description = ""
    summary_blob = ""
    if requirements_summary is not None:
        input_description = _string(requirements_summary.get("input_description")) or ""
        output_description = (
            _string(requirements_summary.get("output_description")) or ""
        )
        summary_blob = _text_blob(requirements_summary)

    folded_input_description = input_description.casefold()
    folded_output_blob = output_description.casefold()
    for required in expected.required_input_summary_terms:
        if required.casefold() not in folded_input_description:
            reasons.append(f"Input summary does not mention {required!r}.")
    for forbidden in expected.forbidden_input_summary_terms:
        if forbidden.casefold() in folded_input_description:
            reasons.append(
                f"Input summary mentions forbidden source term {forbidden!r}."
            )
    for forbidden in expected.forbidden_output_summary_terms:
        if (
            forbidden.casefold() in folded_output_blob
            or forbidden.casefold() in summary_blob
        ):
            reasons.append(
                f"Output/decision summary mentions forbidden term {forbidden!r}."
            )

    for expected_binding in expected.expected_question_bindings:
        reasons.extend(_question_binding_failures(plan=plan, expected=expected_binding))

    return ("fail" if reasons else "pass"), reasons, terminal, input_types, form_fields


def _write_json(path: Path, payload: JsonValue) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_create_case(
    client: AIBuilderClient,
    *,
    case: LiveEvalCase,
    model_id: str,
    output_dir: Path,
) -> LiveEvalResult:
    case_dir = output_dir / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    session = client.create_session(force_new=True)
    _write_json(case_dir / "session.json", session)
    session_id = _string(session.get("session_id"))
    if session_id is None:
        raise LiveEvalError(
            f"{case.case_id}: create session response missing session_id"
        )

    all_events: list[StreamEvent] = []
    next_message = case.prompt
    next_answer: JsonObject | None = None
    plan: JsonObject | None = None
    requirements_summary: JsonObject | None = None

    for turn_index in range(1, case.max_turns + 1):
        events = client.send_message(
            session_id=session_id,
            message=next_message,
            model_id=model_id,
            question_answer=next_answer,
        )
        all_events.extend(events)
        _write_json(
            case_dir / f"turn-{turn_index:02d}-events.json",
            [asdict(event) for event in events],
        )
        plan = _plan_from_events(events) or plan
        requirements_summary = (
            _latest_requirements_summary(events) or requirements_summary
        )
        if plan is not None:
            break

        question = _latest_question(events)
        if question is not None:
            question_id = _string(question.get("question_id"))
            desired = (
                case.question_answers.get(question_id or "")
                if question_id is not None
                else None
            )
            if desired is None:
                break
            selected = _question_answer_payload(question, desired)
            if selected is None:
                break
            next_message, next_answer = selected
            continue

        if requirements_summary is not None:
            next_message = "Yes, use these requirements."
            next_answer = _requirements_confirm_answer(requirements_summary)
            continue

        break

    if requirements_summary is not None:
        _write_json(case_dir / "requirements-summary.json", requirements_summary)
    if plan is not None:
        _write_json(case_dir / "plan.json", plan)
        plan_id = _plan_id(plan)
        if plan_id is not None:
            fetched_plan = client.get_plan(plan_id)
            _write_json(case_dir / "plan-fetched.json", fetched_plan)
            plan = fetched_plan

    verdict, reasons, terminal, input_types, form_fields = _evaluate_plan_case(
        case,
        plan=plan,
        events=all_events,
        requirements_summary=requirements_summary,
    )
    result = LiveEvalResult(
        case_id=case.case_id,
        title=case.title,
        verdict=verdict,
        reasons=reasons,
        session_id=session_id,
        plan_id=_plan_id(plan),
        plan_status=_plan_status(plan),
        event_sequence=[event.event for event in all_events],
        terminal_output=terminal,
        input_types=input_types,
        form_fields=form_fields,
        requirements_summary=requirements_summary,
        questions=_questions_from_events(all_events),
        raw_artifact_dir=str(case_dir),
    )
    _write_json(case_dir / "result.json", cast(JsonValue, asdict(result)))
    return result


def _run_revise_case(
    client: AIBuilderClient,
    *,
    case: LiveEvalCase,
    seed_result: LiveEvalResult,
    output_dir: Path,
) -> LiveEvalResult:
    case_dir = output_dir / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    seed_plan_id = seed_result.plan_id
    if seed_plan_id is None:
        result = LiveEvalResult(
            case_id=case.case_id,
            title=case.title,
            verdict="incomplete",
            reasons=["No seed plan was available for revise/edit evaluation."],
            raw_artifact_dir=str(case_dir),
        )
        _write_json(case_dir / "result.json", cast(JsonValue, asdict(result)))
        return result
    if seed_result.plan_status != "proposed":
        result = LiveEvalResult(
            case_id=case.case_id,
            title=case.title,
            verdict="fail",
            reasons=[
                "Seed plan was not proposed; revise requires a proposed plan. "
                f"Observed {seed_result.plan_status or 'missing status'}."
            ],
            plan_id=seed_plan_id,
            plan_status=seed_result.plan_status,
            raw_artifact_dir=str(case_dir),
        )
        _write_json(case_dir / "result.json", cast(JsonValue, asdict(result)))
        return result

    try:
        revised_plan = client.revise_plan(seed_plan_id)
    except httpx.HTTPStatusError as error:
        result = LiveEvalResult(
            case_id=case.case_id,
            title=case.title,
            verdict="fail",
            reasons=[
                "Revise endpoint returned "
                f"{error.response.status_code}: {error.response.text[:500]}"
            ],
            plan_id=seed_plan_id,
            plan_status=seed_result.plan_status,
            raw_artifact_dir=str(case_dir),
        )
        _write_json(case_dir / "result.json", cast(JsonValue, asdict(result)))
        return result

    _write_json(case_dir / "revise-response.json", revised_plan)
    revised_plan_id = _string(revised_plan.get("plan_id"))
    result = LiveEvalResult(
        case_id=case.case_id,
        title=case.title,
        verdict="pass"
        if revised_plan_id and revised_plan_id != seed_plan_id
        else "fail",
        reasons=(
            ["Revise returned a replacement plan."]
            if revised_plan_id and revised_plan_id != seed_plan_id
            else ["Revise did not return a replacement plan id."]
        ),
        plan_id=seed_plan_id,
        plan_status=seed_result.plan_status,
        revised_plan_id=revised_plan_id,
        revised_plan_status=_plan_status(revised_plan),
        terminal_output=_terminal_output(revised_plan),
        input_types=_input_types(revised_plan),
        form_fields=_form_fields(revised_plan),
        raw_artifact_dir=str(case_dir),
    )
    _write_json(case_dir / "result.json", cast(JsonValue, asdict(result)))
    return result


def _warmup(client: AIBuilderClient, *, model_id: str, output_dir: Path) -> JsonObject:
    warmup_dir = output_dir / "warmup"
    warmup_dir.mkdir(parents=True, exist_ok=True)
    flows = client.get_json(f"{API_PREFIX}/flows/?space_id={client.space_id}")
    _write_json(warmup_dir / "flows.json", flows)
    session = client.create_session(force_new=True)
    _write_json(warmup_dir / "session.json", session)
    session_id = _string(session.get("session_id"))
    if session_id is None:
        raise LiveEvalError("Warmup session missing session_id.")

    events = client.send_message(
        session_id=session_id,
        message="Create a tiny flow that summarizes pasted meeting notes into bullet points.",
        model_id=model_id,
    )
    _write_json(warmup_dir / "events.json", [asdict(event) for event in events])
    cancel_result = client.cancel_session(session_id)
    _write_json(warmup_dir / "cancel.json", cancel_result)
    return {
        "flow_count": flows.get("count"),
        "warmup_session_id": session_id,
        "warmup_events": [event.event for event in events],
    }


def _cases() -> list[LiveEvalCase]:
    return [
        LiveEvalCase(
            case_id="C1_vague_meeting_notes",
            title="Vague meeting notes action items",
            prompt=(
                "I want something that helps me summarize meeting notes and produce "
                "clear action items for my team."
            ),
            expected=ExpectedOutcome(
                allowed_question_ids_without_plan=(
                    "input_material_mode",
                    "final_output_mode",
                    "flow_input_architecture",
                )
            ),
            max_turns=2,
        ),
        LiveEvalCase(
            case_id="C2_json_with_document_words",
            title="Strict JSON output despite document source words",
            prompt=(
                "Build a flow that reads a long procurement document and returns "
                "strict JSON with ranked offers, risk flags, and missing information. "
                "Do not create Word, DOCX, PDF, or a document output."
            ),
            expected=ExpectedOutcome(
                terminal_output="structured_json",
                required_input_types=("document",),
                forbidden_output_types=("docx", "pdf"),
                forbidden_output_summary_terms=(
                    "docx",
                    "word",
                    "pdf",
                    "document output",
                ),
            ),
            question_answers={
                "input_material_mode": ("documents",),
                "final_output_mode": ("structured_json",),
            },
        ),
        LiveEvalCase(
            case_id="C3_audio_to_docx_report",
            title="Audio meeting transcription to DOCX report",
            prompt=(
                "Create a flow that transcribes meeting audio, extracts ten topic "
                "sections, and produces a DOCX meeting report."
            ),
            expected=ExpectedOutcome(
                terminal_output="docx_document",
                required_input_types=("audio",),
                forbidden_input_types=("document", "file"),
                required_input_summary_terms=("audio",),
                forbidden_input_summary_terms=("document", "documents", "dokument"),
                expected_question_bindings=(
                    ExpectedQuestionBinding(
                        step_role="writing_or_materialization",
                        require_text_ref=True,
                        require_structured_field_ref=True,
                        forbid_broad_structured_ref=True,
                    ),
                ),
            ),
            question_answers={
                "input_material_mode": ("audio",),
                "final_output_mode": ("docx_document",),
                "docx_output_mode": ("generated_docx",),
                "structured_analysis_need": ("use_structured_analysis",),
            },
        ),
        LiveEvalCase(
            case_id="C4_runtime_form_fields",
            title="Runtime form fields plus optional uploads",
            prompt=(
                "Create a flow where the user supplies customer name, analysis "
                "request, and optional uploaded files, then the flow produces a "
                "structured answer."
            ),
            expected=ExpectedOutcome(
                terminal_output="structured_text",
                required_form_fields=("customer_name", "analysis_request"),
            ),
            question_answers={
                "input_material_mode": ("text_and_documents",),
                "final_output_mode": ("structured_text",),
                "runtime_metadata_fields": ("detailed_case_metadata",),
            },
        ),
    ]


def _dedicated_seed_case() -> LiveEvalCase:
    return LiveEvalCase(
        case_id="C5_seed_text_summary_plan",
        title="Seed plan for revise/edit",
        prompt=(
            "Create a small flow that takes pasted meeting notes and returns a "
            "short structured text summary with decisions and action items."
        ),
        expected=ExpectedOutcome(
            terminal_output="structured_text",
            forbidden_output_types=("docx", "pdf"),
        ),
        question_answers={
            "input_material_mode": ("text",),
            "final_output_mode": ("structured_text",),
        },
    )


def _append_ledger(
    *,
    ledger_path: Path,
    output_dir: Path,
    warmup: JsonObject,
    model_id: str,
    model_name: str | None,
    results: list[LiveEvalResult],
) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "",
        "## T026a Five-Case Authenticated Live Eval",
        "",
        f"Date: {now}.",
        "",
        f"Raw local artifacts: `{output_dir}`.",
        "",
        f"Model: `{model_name or 'unknown'}` (`{model_id}`).",
        "",
        "Warmup:",
        "",
        "```json",
        json.dumps(warmup, ensure_ascii=False, indent=2),
        "```",
        "",
        "| Case | Verdict | Session | Plan | Plan Status | Terminal Output | Inputs | Form Fields | Reasons |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            "| {case} | {verdict} | {session} | {plan} | {status} | {terminal} | {inputs} | "
            "{fields} | {reasons} |".format(
                case=result.case_id,
                verdict=result.verdict,
                session=result.session_id or "",
                plan=result.plan_id or result.revised_plan_id or "",
                status=result.plan_status or result.revised_plan_status or "",
                terminal=result.terminal_output or "",
                inputs=", ".join(result.input_types),
                fields=", ".join(result.form_fields),
                reasons="<br>".join(result.reasons) if result.reasons else "",
            )
        )

    failed = [result for result in results if result.verdict != "pass"]
    lines.extend(
        [
            "",
            "T026a verdict:",
            "",
            (
                "All five cases passed. Normal-User Output Quality still requires "
                "post-review before moving from 8 to 9."
                if not failed
                else (
                    "At least one case did not pass. T026b must choose exactly one "
                    "canonical owner before product code changes."
                )
            ),
            "",
        ]
    )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def run(config: RunnerConfig) -> int:
    output_dir = config.output_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=False)

    client = AIBuilderClient(config)
    try:
        models_payload = client.get_json(f"{API_PREFIX}/completion-models/")
        _write_json(output_dir / "models.json", models_payload)
        model_id = _choose_model_id(models_payload)
        model_name = _model_name(models_payload, model_id)
        warmup = _warmup(client, model_id=model_id, output_dir=output_dir)

        results: list[LiveEvalResult] = []
        for case in _cases():
            result = _run_create_case(
                client,
                case=case,
                model_id=model_id,
                output_dir=output_dir,
            )
            results.append(result)
            time.sleep(config.inter_case_delay_seconds)

        seed_result = _run_create_case(
            client,
            case=_dedicated_seed_case(),
            model_id=model_id,
            output_dir=output_dir,
        )
        time.sleep(config.inter_case_delay_seconds)

        revise_case = LiveEvalCase(
            case_id="C5_revise_edit_flow",
            title="Revise/edit flow through public API",
            prompt="Revise the current plan while keeping the current description.",
            expected=ExpectedOutcome(),
        )
        results.append(
            _run_revise_case(
                client,
                case=revise_case,
                seed_result=seed_result,
                output_dir=output_dir,
            )
        )

        results_payload = cast(JsonValue, [asdict(result) for result in results])
        _write_json(output_dir / "results.json", results_payload)
        _append_ledger(
            ledger_path=config.ledger_path,
            output_dir=output_dir,
            warmup=warmup,
            model_id=model_id,
            model_name=model_name,
            results=results,
        )

        return 0 if all(result.verdict == "pass" for result in results) else 1
    finally:
        client.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ENEO_API_BASE_URL", DEFAULT_BASE_URL),
        help="Base URL for the local API.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where raw local artifacts are written.",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Markdown ledger to append sanitized results to.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-stream-events", type=int, default=200)
    parser.add_argument("--inter-case-delay-seconds", type=float, default=2.0)
    return parser.parse_args()


def _config_from_args(args: argparse.Namespace) -> RunnerConfig:
    return RunnerConfig(
        base_url=cast(str, args.base_url),
        api_key=_required_env("ENEO_API_KEY", "API_KEY"),
        space_id=_required_env("ENEO_FLOW_TEST_SPACE_ID"),
        output_root=cast(Path, args.output_root),
        ledger_path=cast(Path, args.ledger),
        per_case_timeout_seconds=cast(float, args.timeout_seconds),
        max_stream_events=cast(int, args.max_stream_events),
        inter_case_delay_seconds=cast(float, args.inter_case_delay_seconds),
    )


def _required_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    if len(names) == 1:
        raise LiveEvalError(f"Missing required environment variable: {names[0]}")
    raise LiveEvalError(
        "Missing required environment variable: one of " + ", ".join(names)
    )


def main() -> int:
    try:
        return run(_config_from_args(_parse_args()))
    except Exception as error:
        print(f"flow_ai_builder_live_eval failed: {error}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
