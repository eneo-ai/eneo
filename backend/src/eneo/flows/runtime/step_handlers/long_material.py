"""Complete a step whose input does not fit its model by digesting it first.

A step opts in with ``input_config.long_material``. Its input is measured the
way the provider request will be; input that fits goes to the ordinary step
completion unchanged. Input that does not is read in segments by the bounded
map-reduce core, every call with the step's own model and assistant, through
the same provider path, deadline and cancellation as the step's own request.
The step's own call then answers over the merged notes under its output
contract, and the result records what the digest covered.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from eneo.ai_models.completion_models.completion_model import Completion, ModelKwargs
from eneo.completion_models.application.map_reduce import (
    DigestBudgets,
    DigestDeadlineExceeded,
    Stage,
    Usage,
    batch_reduce_prompt,
    map_prompt,
    plan_segments,
    run_digest,
)
from eneo.completion_models.domain.model_capacity import UnknownModelCapacityError
from eneo.completion_models.domain.request_preflight import (
    CompletionRequestPreflight,
)
from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.long_material import (
    DIGEST_DIAGNOSTIC_CODE,
    PARTIAL_COVERAGE_DIAGNOSTIC_CODE,
    STAGE_DEFAULTS,
    DigestCallLimits,
    DigestCallRecord,
    DigestSource,
    LongMaterialCoverage,
    SourceCandidate,
    admit_digest,
    build_coverage,
    digest_budgets,
    digest_instruction,
    digest_message,
    digest_time_limits,
    final_call,
    final_question,
    final_question_frame,
    is_map_call,
    map_call_target,
    minimum_digest_calls,
    minimum_digest_input_tokens,
    partial_coverage_error,
    partial_coverage_message,
    partial_coverage_outcome,
    partition_digest_sources,
    reduce_call,
    text_reference,
    without_direct_path,
)
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.provider_call import DigestCallInput
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import sum_complete_token_counts
from eneo.flows.runtime.execution_heartbeat import FlowExecutionOwnershipLost
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.run_cancellation import FlowStepCancelledError
from eneo.flows.runtime.step_deadline import (
    StepDeadline,
    StepDeadlineExceeded,
    record_step_progress,
)
from eneo.flows.runtime.step_execution_runtime import (
    PreparedCompletionCall,
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
    attach_typed_failure_context,
    call_assistant_with_timeout,
    complete_step_execution,
)
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.main.exceptions import TypedIOValidationException

logger = logging.getLogger(__name__)


class _DigestStopped(Exception):
    """A digest call refused because the step is already ending."""


class _CeilingReached(Exception):
    """A digest call refused by the organization's mapped-execution ceiling."""


async def complete_with_long_material(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    prepared_step: PreparedAssistantStep,
    mapped_execution_policy: FlowMappedExecutionPolicy,
) -> StepExecutionOutput:
    """Complete the step, digesting its input first when it does not fit."""
    prepared = prepared_step.prepared
    deps = prepared_step.deps
    refused = await _refused_preflight(prepared=prepared, deps=deps)
    if refused is None:
        return await complete_step_execution(
            step=step, run=run, state=state, prepared=prepared, deps=deps
        )
    return await _digest_and_complete(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
        refused=refused,
        policy=mapped_execution_policy,
    )


async def _refused_preflight(
    *, prepared: PreparedStepExecution, deps: StepExecutionRuntimeDeps
) -> CompletionRequestPreflight | None:
    """The step request's measurement when its input does not fit, else None.

    Only an input that does not fit is digested. Everything else, including
    a model without declared limits or input sent as files, takes the
    ordinary path, which reports it exactly as before.
    """
    completion_call = prepared.completion_call
    if completion_call is None or prepared.llm_files:
        return None
    try:
        preview = await prepared.assistant.preflight_response_context(
            question=completion_call.question,
            completion_service=deps.completion_service,
            files=prepared.llm_files,
            prompt_override=completion_call.effective_prompt,
            version=completion_call.assistant_context_version,
            model_kwargs=completion_call.preferred_model_kwargs,
            capability_fallback_prompt=completion_call.capability_fallback_prompt,
            useful_output_reserve_tokens=completion_call.useful_output_reserve_tokens,
        )
    except UnknownModelCapacityError:
        return None
    if preview.refusal != "current_request_input_does_not_fit":
        return None
    return preview


def _model_name(prepared: PreparedStepExecution) -> str:
    completion_model = prepared.assistant.completion_model
    if completion_model is None:
        return ""
    explicit = getattr(completion_model, "litellm_model_name", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return completion_model.name or ""


def _source_candidates(
    *, prepared: PreparedStepExecution, state: RunExecutionState
) -> list[SourceCandidate]:
    """The uploaded files and earlier step outputs the input was built from."""
    step_input = prepared.step_input
    candidates: list[SourceCandidate] = []
    for file in step_input.files or []:
        text = getattr(file, "text", None)
        if not isinstance(text, str) or not text.strip():
            continue
        content = text.strip()
        name = getattr(file, "name", None)
        candidates.append(
            SourceCandidate(
                title=name if isinstance(name, str) and name.strip() else "File",
                text=content,
                reference={
                    **text_reference("file", content),
                    "file_id": str(getattr(file, "id", "")),
                },
            )
        )
    orders = {result.step_id: result.step_order for result in state.prior_results}
    for material in step_input.materials:
        if not material.text.strip():
            continue
        order = orders.get(material.source_step_id)
        name = state.step_names_by_order.get(order) if order is not None else None
        title = (
            f"Step {order}: {name}"
            if order is not None and name
            else f"Step {order}"
            if order is not None
            else "Earlier step"
        )
        candidates.append(
            SourceCandidate(
                title=title,
                text=material.text,
                reference=material.reference.model_dump(mode="json"),
            )
        )
    return candidates


@dataclass
class _Rooms:
    map_overhead: int
    budgets: DigestBudgets


async def _measure_overhead(
    *,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
    prompt: str,
    question: str,
    model_kwargs: ModelKwargs,
    reserve: int,
    version: int = 1,
    capability_fallback_prompt: str | None = None,
) -> int:
    preview = await prepared.assistant.preflight_response_context(
        question=question,
        completion_service=deps.completion_service,
        files=[],
        prompt_override=prompt,
        version=version,
        model_kwargs=model_kwargs,
        capability_fallback_prompt=capability_fallback_prompt,
        useful_output_reserve_tokens=reserve,
    )
    return max(package.input_reserve.tokens for package in preview.packages)


async def _measure_rooms(
    *,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
    completion_call: PreparedCompletionCall,
    refused: CompletionRequestPreflight,
    instruction: str,
    digest_kwargs: ModelKwargs,
    sources: Sequence[DigestSource],
) -> _Rooms | None:
    capacity = refused.capacity
    max_output = capacity.require_output_tokens()

    def allowance(reserve: int) -> int:
        return capacity.input_allowance(output_reserve_tokens=reserve, safety_tokens=0)

    map_reserve = min(STAGE_DEFAULTS.map_max_tokens, max_output)
    map_overhead = await _measure_overhead(
        prepared=prepared,
        deps=deps,
        prompt=map_prompt(instruction, STAGE_DEFAULTS.map_words),
        question="",
        model_kwargs=digest_kwargs,
        reserve=map_reserve,
    )
    reduce_reserve = min(STAGE_DEFAULTS.batch_max_tokens, max_output)
    reduce_overhead = await _measure_overhead(
        prepared=prepared,
        deps=deps,
        prompt=batch_reduce_prompt(instruction, STAGE_DEFAULTS.batch_words),
        question="",
        model_kwargs=digest_kwargs,
        reserve=reduce_reserve,
    )
    # The answer over the notes keeps room for a full answer, not only the
    # step's minimum output.
    final_reserve = max(
        completion_call.useful_output_reserve_tokens,
        min(STAGE_DEFAULTS.final_max_tokens, max_output),
    )
    final_overhead = await _measure_overhead(
        prepared=prepared,
        deps=deps,
        prompt=completion_call.effective_prompt,
        question=f"{final_question_frame(sources)}Notes:\n\n",
        model_kwargs=completion_call.preferred_model_kwargs,
        reserve=final_reserve,
        version=completion_call.assistant_context_version,
        capability_fallback_prompt=completion_call.capability_fallback_prompt,
    )
    budgets = digest_budgets(
        map_room=allowance(map_reserve) - map_overhead,
        reduce_room=allowance(reduce_reserve) - reduce_overhead,
        final_room=allowance(final_reserve) - final_overhead,
    )
    if budgets is None:
        return None
    return _Rooms(map_overhead=map_overhead, budgets=budgets)


def _window_too_small_error(
    *,
    step: RuntimeStep,
    refused: CompletionRequestPreflight,
    completion_call: PreparedCompletionCall,
) -> TypedIOValidationException:
    estimated = min(package.input_reserve.tokens for package in refused.packages)
    allowance = refused.capacity.input_allowance(
        output_reserve_tokens=completion_call.useful_output_reserve_tokens,
        safety_tokens=0,
    )
    return TypedIOValidationException(
        f"Step {step.step_order}: packaged model input uses about {estimated} "
        f"tokens, exceeding the selected model window of {allowance} tokens, and "
        "the window is too small to read the input in parts. Use a "
        "larger-context model or reduce the step input.",
        code=FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value,
    )


def _response_text_and_usage(response: Any, *, model_name: str) -> tuple[str, Usage]:
    completion = response.completion
    finish_reason: str | None = None
    reasoning_tokens = 0
    if isinstance(completion, str):
        text = completion
    elif isinstance(completion, Completion):
        text = completion.text or ""
        finish_reason = completion.finish_reason
        reasoning_tokens = completion.reasoning_token_count or 0
    else:
        text = str(completion)
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    input_tokens = (
        prompt_tokens if isinstance(prompt_tokens, int) else response.total_token_count
    )
    output_tokens = (
        completion_tokens
        if isinstance(completion_tokens, int)
        else count_tokens(text, model_name) + reasoning_tokens
    )
    return text, Usage(
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        length_stopped=finish_reason == "length",
    )


@dataclass
class _DigestCalls:
    """The provider side of one digest: every call through the step's own
    provider path, one at a time, under the step's ceilings and deadline.

    The core treats a failed call as a gap in coverage and carries on. A
    cancellation, a lost run or an expired step is not a gap: it is kept in
    ``fatal``, every later call is refused, and the runtime raises it once
    the core returns.
    """

    step: RuntimeStep
    run: FlowRun
    state: RunExecutionState
    prepared: PreparedStepExecution
    deps: StepExecutionRuntimeDeps
    model_kwargs: ModelKwargs
    model_name: str
    max_output_tokens: int
    instruction: str
    budgets: DigestBudgets
    keys: dict[str, int]
    limits: DigestCallLimits
    step_deadline: StepDeadline
    digest_deadline: StepDeadline
    records: list[DigestCallRecord] = field(default_factory=list[DigestCallRecord])
    fatal: BaseException | None = None
    notes: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def count(self, text: str) -> int:
        return count_tokens(text, self.model_name)

    async def complete_map(
        self, system: str, user: str, max_tokens: int
    ) -> tuple[str, Usage]:
        call = (
            map_call_target(user, self.keys)
            if is_map_call(system, instruction=self.instruction, budgets=self.budgets)
            else None
        )
        return await self._send(
            call or reduce_call(user, self.keys), system, user, max_tokens
        )

    async def complete_reduce(
        self, system: str, user: str, max_tokens: int
    ) -> tuple[str, Usage]:
        return await self._send(reduce_call(user, self.keys), system, user, max_tokens)

    async def capture_notes(
        self, system: str, user: str, max_tokens: int
    ) -> tuple[str, Usage]:
        # The core's answer stage hands over the merged notes; the step's own
        # call writes the answer under its output contract.
        del system, max_tokens
        self.notes = user
        return user, Usage()

    async def should_stop(self) -> bool:
        if self.fatal is not None:
            return True
        probe = self.deps.run_cancelled
        if probe is None:
            return False
        try:
            return await probe(
                run_id=self.run.id,
                flow_id=self.run.flow_id,
                tenant_id=self.run.tenant_id,
            )
        except Exception:
            logger.warning(
                "flow_long_material.cancel_probe_failed run_id=%s step_order=%d",
                self.run.id,
                self.step.step_order,
                exc_info=True,
            )
            return False

    async def report(self, done: int, planned: int, stage: Stage) -> None:
        record_step_progress(
            f"long material: {done} of {planned} segments read ({stage})",
            completed_items=done,
            total_items=planned,
        )

    async def _send(
        self, call: DigestCallInput, system: str, user: str, max_tokens: int
    ) -> tuple[str, Usage]:
        async with self.lock:
            if self.fatal is not None:
                raise _DigestStopped()
            if self.digest_deadline.expired():
                raise DigestDeadlineExceeded()
            if not self.limits.admit(self.count(system) + self.count(user)):
                raise _CeilingReached()
            try:
                response = await call_assistant_with_timeout(
                    step=self.step,
                    run=self.run,
                    state=self.state,
                    prepared=self.prepared,
                    deps=replace(
                        self.deps, digest_call=call, summarization_budget=None
                    ),
                    question=user,
                    model_kwargs=self.model_kwargs,
                    info_blob_chunks=[],
                    prompt_override=system,
                    version=1,
                    provider_call_reason="initial",
                    deadline=self.digest_deadline,
                    useful_output_reserve_tokens=min(
                        max_tokens, self.max_output_tokens
                    ),
                )
            except StepDeadlineExceeded as exc:
                if self.step_deadline.expired():
                    self.fatal = exc
                    raise
                self.records.append(DigestCallRecord(call=call, outcome="failed"))
                raise DigestDeadlineExceeded() from exc
            except (
                FlowStepCancelledError,
                FlowExecutionOwnershipLost,
                FlowRuntimeInvariantError,
            ) as exc:
                self.fatal = exc
                raise
            except Exception:
                self.records.append(DigestCallRecord(call=call, outcome="failed"))
                raise
        text, usage = _response_text_and_usage(response, model_name=self.model_name)
        self.records.append(
            DigestCallRecord(
                call=call,
                outcome="cut" if usage.length_stopped else "ok",
                num_tokens_input=usage.input_tokens,
                num_tokens_output=usage.output_tokens,
            )
        )
        return text, usage


async def _digest_and_complete(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    prepared: PreparedStepExecution,
    deps: StepExecutionRuntimeDeps,
    refused: CompletionRequestPreflight,
    policy: FlowMappedExecutionPolicy,
) -> StepExecutionOutput:
    completion_call = prepared.completion_call
    if completion_call is None:
        raise FlowRuntimeInvariantError(
            "Long material requires a frozen completion call."
        )

    def fail(exc: TypedIOValidationException) -> TypedIOValidationException:
        return attach_typed_failure_context(
            exc,
            input_payload_for_result=prepared.input_payload_for_result,
            effective_prompt=completion_call.effective_prompt,
        )

    if getattr(prepared.assistant, "mcp_servers", []):
        raise fail(
            TypedIOValidationException(
                f"Step {step.step_order}: the input exceeds the model's input "
                "capacity, and reading it in parts is not supported for an "
                "assistant with external MCP tools; remove them from the step's "
                "assistant or reduce the input.",
                code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
            )
        )
    question = completion_call.question
    sources = partition_digest_sources(
        question, _source_candidates(prepared=prepared, state=state)
    )
    instruction = digest_instruction(
        prepared.effective_prompt,
        resolve_format_spec(step.output_type).prompt_instructions(step.output_contract),
    )
    digest_kwargs = completion_call.preferred_model_kwargs.model_copy(
        update={"response_format": None}
    )
    rooms = await _measure_rooms(
        prepared=prepared,
        deps=deps,
        completion_call=completion_call,
        refused=refused,
        instruction=instruction,
        digest_kwargs=digest_kwargs,
        sources=sources,
    )
    if rooms is None:
        raise fail(
            _window_too_small_error(
                step=step, refused=refused, completion_call=completion_call
            )
        )
    model_name = _model_name(prepared)

    def count(text: str) -> int:
        return count_tokens(text, model_name)

    budgets = rooms.budgets
    plan = without_direct_path(
        plan_segments([source.item() for source in sources], budgets, count)
    )
    fallback_possible = completion_call.capability_fallback_model_kwargs is not None
    try:
        admit_digest(
            step_order=step.step_order,
            needed_calls=minimum_digest_calls(
                plan, fallback_call_possible=fallback_possible
            ),
            needed_input_tokens=minimum_digest_input_tokens(
                plan, map_overhead_tokens=rooms.map_overhead
            ),
            call_ceiling=policy.max_provider_calls_per_mapped_step,
            token_ceiling=policy.max_estimated_input_tokens_per_mapped_step,
        )
    except TypedIOValidationException as exc:
        raise fail(exc) from None
    call_ceiling = policy.max_provider_calls_per_mapped_step
    assert call_ceiling is not None  # admit_digest refuses a disabled ceiling
    step_deadline = deps.deadline or StepDeadline.start(
        deps.llm_request_timeout_seconds
    )
    clock = asyncio.get_running_loop().time
    time_limits = digest_time_limits(
        now=clock(),
        expires_at=step_deadline.expires_at,
        budget_seconds=step_deadline.budget_seconds,
    )
    calls = _DigestCalls(
        step=step,
        run=run,
        state=state,
        prepared=prepared,
        deps=deps,
        model_kwargs=digest_kwargs,
        model_name=model_name,
        max_output_tokens=refused.capacity.require_output_tokens(),
        instruction=instruction,
        budgets=budgets,
        keys={source.key: source.index for source in sources},
        limits=DigestCallLimits(
            call_ceiling=call_ceiling,
            token_ceiling=policy.max_estimated_input_tokens_per_mapped_step,
            reserved_calls=1 + int(fallback_possible),
        ),
        step_deadline=step_deadline,
        digest_deadline=StepDeadline(
            budget_seconds=step_deadline.budget_seconds,
            started_at=step_deadline.started_at,
            expires_at=time_limits.deadline,
            invocation_limited=step_deadline.invocation_limited,
        ),
    )
    if deps.logger is not None:
        deps.logger.info(
            "flow_long_material.digest_started run_id=%s step_order=%d sources=%d "
            "segments=%d input_tokens=%d segment_tokens=%d reduce_input_tokens=%d",
            run.id,
            step.step_order,
            len(sources),
            plan.total_segments,
            plan.total_tokens,
            budgets.segment_tokens,
            budgets.reduce_input_tokens,
        )
    result = await run_digest(
        plan,
        calls.complete_reduce,
        instruction=instruction,
        budgets=budgets,
        count=count,
        deadline=time_limits.deadline,
        reduce_reserve_seconds=time_limits.reduce_reserve_seconds,
        should_stop=calls.should_stop,
        map_batch=1,
        now=clock,
        complete_map=calls.complete_map,
        on_progress=calls.report,
        complete_final=calls.capture_notes,
    )
    if calls.fatal is not None:
        raise calls.fatal
    if result.coverage == "cancelled":
        raise FlowStepCancelledError("Run was cancelled during step execution.")
    notes = calls.notes or ""
    coverage = build_coverage(
        result=result,
        sources=sources,
        plan=plan,
        budgets=budgets,
        calls=calls.records,
        extra_reasons=(calls.limits.refused,) if calls.limits.refused else (),
        refused_input_tokens=min(
            package.input_reserve.tokens for package in refused.packages
        ),
        max_input_tokens=refused.capacity.input_allowance(
            output_reserve_tokens=completion_call.useful_output_reserve_tokens,
            safety_tokens=0,
        ),
        notes=notes or None,
    )
    if deps.logger is not None:
        deps.logger.info(
            "flow_long_material.digest_done run_id=%s step_order=%d coverage=%s "
            "reasons=%s map_calls=%d reduce_calls=%d failed_calls=%d",
            run.id,
            step.step_order,
            coverage.coverage,
            ",".join(coverage.reasons),
            coverage.map_calls,
            coverage.reduce_calls,
            coverage.failed_calls,
        )
    record = coverage.model_dump(mode="json")
    input_payload = {**prepared.input_payload_for_result, "long_material": record}
    outcome = partial_coverage_outcome(
        coverage, review_configured=step.review_policy is not None
    )
    if outcome == "fail":
        raise attach_typed_failure_context(
            partial_coverage_error(step_order=step.step_order, coverage=coverage),
            input_payload_for_result=input_payload,
            effective_prompt=completion_call.effective_prompt,
        )
    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=replace(
            prepared,
            completion_call=replace(
                completion_call,
                question=final_question(sources=sources, notes=notes),
                preflight=None,
                selected_package=None,
            ),
            input_payload_for_result=input_payload,
        ),
        deps=replace(deps, digest_call=final_call(notes, calls.keys)),
    )
    return _with_coverage(
        output=output, step=step, coverage=coverage, records=calls.records
    )


def _with_coverage(
    *,
    output: StepExecutionOutput,
    step: RuntimeStep,
    coverage: LongMaterialCoverage,
    records: Sequence[DigestCallRecord],
) -> StepExecutionOutput:
    """The final call's output, accounting for every digest call."""
    completed = [record for record in records if record.outcome != "failed"]
    diagnostic = (
        StepDiagnostic(
            code=DIGEST_DIAGNOSTIC_CODE,
            message=digest_message(step_order=step.step_order, coverage=coverage),
            severity="info",
        )
        if coverage.coverage == "complete"
        else StepDiagnostic(
            code=PARTIAL_COVERAGE_DIAGNOSTIC_CODE,
            message=partial_coverage_message(
                step_order=step.step_order, coverage=coverage
            ),
            severity="warning",
        )
    )
    return replace(
        output,
        num_tokens_input=sum_complete_token_counts(
            [
                *(record.num_tokens_input for record in completed),
                output.num_tokens_input,
            ]
        ),
        num_tokens_output=sum_complete_token_counts(
            [
                *(record.num_tokens_output for record in completed),
                output.num_tokens_output,
            ]
        ),
        model_parameters_json={
            **output.model_parameters_json,
            "long_material_mode": "digest",
        },
        diagnostics=[diagnostic, *output.diagnostics],
        long_material=coverage.model_dump(mode="json"),
    )


__all__ = ["complete_with_long_material"]
