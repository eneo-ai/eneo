"""Speaker-mapping step: an LLM proposes who each diarized speaker is.

The step reads the previous step's transcript, asks the completion model for a
label-to-participant mapping, and emits both the mapping (structured) and the
transcript with names applied (text). The step's mandatory edit review then
lets a person confirm or correct the proposal before later steps use it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from eneo.flows.domain.speaker_labels import (
    apply_speaker_names,
    build_opening_excerpt,
    build_speaker_inventory,
)
from eneo.flows.domain.speaker_mapping_config import (
    speaker_mapping_infer_names,
    speaker_mapping_participants_field,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from eneo.flows.flow_run_provenance import FlowResolvedInputEdge
from eneo.flows.output_modes import speaker_mapping_violation
from eneo.flows.runtime.speaker_mapping_runtime import (
    SpeakerMappingValidationError,
    build_speaker_mapping_question,
    mapping_to_names,
    resolve_participants,
    speaker_mapping_instructions,
    validate_speaker_mapping,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    attach_typed_failure_context,
    build_prepared_completion_call,
    complete_step_execution,
)
from eneo.flows.runtime.step_handlers.base import (
    ActivatePreparedAssistantStepsFn,
    PreparedAssistantStep,
    PreviewAssistantStepFn,
)
from eneo.main.exceptions import TypedIOValidationException

PersistTranscriptFn = Callable[[FlowRun, str], Awaitable[None]]
ActivateResolvedInputEdgesFn = Callable[
    [FlowRun, RuntimeStep, RunExecutionState, int, tuple[FlowResolvedInputEdge, ...]],
    Awaitable[None],
]

SPEAKER_MAPPING_PAYLOAD_KEY = "speaker_mapping"


async def _no_rag(
    **_: object,
) -> tuple[list[Any], dict[str, Any] | None, list[StepDiagnostic]]:
    return (
        [],
        {"attempted": False, "status": "skipped", "reason": "speaker_mapping"},
        [],
    )


@dataclass(frozen=True)
class SpeakerMappingStepHandler:
    preview_assistant_step: PreviewAssistantStepFn
    activate_prepared_assistant_steps: ActivatePreparedAssistantStepsFn
    activate_resolved_input_edges: ActivateResolvedInputEdgesFn
    persist_transcript: PersistTranscriptFn
    output_mode: FlowOutputMode = FlowOutputMode.SPEAKER_MAPPING

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
    ) -> StepExecutionResult:
        preview = await self.preview_assistant_step(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            attempt_no=attempt_no,
            requested_file_ids_override=(),
        )
        prepared = preview.prepared
        mode_error = speaker_mapping_violation(
            step_order=step.step_order,
            input_source=step.input_source,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if mode_error is not None:
            raise attach_typed_failure_context(
                TypedIOValidationException(
                    mode_error,
                    code=FlowApiErrorCode.TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION.value,
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=prepared.effective_prompt,
            )

        source_text = prepared.step_input.text
        inventory = build_speaker_inventory(source_text)
        if not inventory and _upstream_diarization_skipped(step, state):
            # The transcription model gave no timestamps, so there are no
            # speakers to map. Pass the transcript through and say so rather
            # than fail a run the author configured correctly.
            return await self._pass_through(
                step=step, run=run, state=state, attempt_no=attempt_no, preview=preview
            )
        if not inventory:
            raise attach_typed_failure_context(
                TypedIOValidationException(
                    f"Step {step.step_order}: the input has no diarized speaker "
                    "labels to map; enable speaker identification on the "
                    "transcription step.",
                    code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=prepared.effective_prompt,
            )
        participants_field = speaker_mapping_participants_field(step.output_config)
        participants = resolve_participants(run.input_payload_json, participants_field)
        infer_names = speaker_mapping_infer_names(step.output_config)

        # The model sees the speaker inventory (plus the conversation's opening
        # when it may infer names), not the whole transcript, and a fixed
        # instruction block; the frozen call is what activation records.
        question = build_speaker_mapping_question(
            inventory=inventory,
            participants=participants,
            opening=build_opening_excerpt(source_text) if infer_names else None,
        )
        fixed_instructions = speaker_mapping_instructions(infer_names=infer_names)
        instructions = (
            f"{prepared.effective_prompt}\n\n{fixed_instructions}"
            if prepared.effective_prompt.strip()
            else fixed_instructions
        )
        call_prepared = replace(
            prepared,
            effective_prompt=instructions,
            step_input=replace(prepared.step_input, text=question),
        )
        call_prepared.completion_call = build_prepared_completion_call(
            step=step, state=state, prepared=call_prepared
        )
        (activated,) = await self.activate_prepared_assistant_steps(
            run,
            step,
            state,
            attempt_no,
            (PreparedAssistantStep(prepared=call_prepared, deps=preview.deps),),
        )
        output = await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=activated.prepared,
            deps=replace(activated.deps, retrieve_rag_chunks=_no_rag),
        )

        try:
            mapping = validate_speaker_mapping(
                output.structured_output,
                inventory=inventory,
                participants=participants,
                allow_free_text=infer_names or not participants,
            )
        except SpeakerMappingValidationError as exc:
            raise attach_typed_failure_context(
                TypedIOValidationException(
                    f"Step {step.step_order}: speaker mapping proposal is invalid: {exc}",
                    code=FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value,
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=instructions,
            ) from exc

        renamed = apply_speaker_names(source_text, mapping_to_names(mapping))
        max_bytes = activated.deps.max_inline_text_bytes
        if max_bytes is not None and len(renamed.encode("utf-8")) > max_bytes:
            # A file-backed output could not be review-edited afterwards.
            raise attach_typed_failure_context(
                TypedIOValidationException(
                    f"Step {step.step_order}: transcript with speaker names exceeds "
                    f"the inline output limit ({max_bytes} bytes).",
                    code=FlowApiErrorCode.TYPED_IO_TRANSCRIPT_TOO_LARGE.value,
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=instructions,
            )
        persisted_text, generated_file_ids = await activated.deps.apply_output_cap(
            text=renamed, run=run, step=step
        )

        source_step_id, source_attempt_no = _source_step_identity(step, state)
        output.input_text = source_text
        output.full_text = renamed
        output.persisted_text = persisted_text
        output.generated_file_ids = generated_file_ids
        output.structured_output = mapping
        output.output_payload_extensions = {
            SPEAKER_MAPPING_PAYLOAD_KEY: {
                "source_step_id": source_step_id,
                "source_step_order": step.step_order - 1,
                "source_attempt_no": source_attempt_no,
                "participants_field": participants_field,
                "participants": participants,
                "infer_names": infer_names,
                "inventory": inventory,
            }
        }
        unmapped = [
            entry["label"] for entry in mapping["speakers"] if entry["name"] is None
        ]
        if unmapped:
            output.diagnostics.append(
                StepDiagnostic(
                    code="speaker_mapping_unmapped_labels",
                    message=(
                        f"Step {step.step_order}: no participant could be proposed "
                        f"for {', '.join(unmapped)}; confirm them in the review."
                    ),
                    severity="warning",
                )
            )

        # Keep the run-level transcript variable in step with the renamed text
        # so later steps using {{transkribering}} see the same names.
        run_payload = run.input_payload_json or {}
        if run_payload.get(FLOW_INPUT_TRANSCRIPTION_KEY) == source_text:
            await self.persist_transcript(run, renamed)
        return StepExecutionResult(output=output)

    async def _pass_through(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        attempt_no: int,
        preview: PreparedAssistantStep,
    ) -> StepExecutionResult:
        prepared = preview.prepared
        # No provider call happens, but the attempt still records what it read.
        await self.activate_resolved_input_edges(
            run, step, state, attempt_no, prepared.resolved_input_edges
        )
        source_text = prepared.step_input.text
        persisted_text, generated_file_ids = await preview.deps.apply_output_cap(
            text=source_text, run=run, step=step
        )
        source_step_id, source_attempt_no = _source_step_identity(step, state)
        diagnostics = [
            *prepared.diagnostics,
            StepDiagnostic(
                code="speaker_mapping_skipped",
                message=(
                    f"Step {step.step_order}: speaker identification was skipped on "
                    "the transcription step (no timestamps from the model), so "
                    "there are no speakers to name; the transcript is passed on "
                    "unchanged."
                ),
                severity="warning",
            ),
        ]
        return StepExecutionResult(
            output=StepExecutionOutput(
                input_text=source_text,
                source_text=prepared.step_input.source_text,
                input_source=prepared.step_input.input_source,
                used_question_binding=prepared.step_input.used_question_binding,
                full_text=source_text,
                persisted_text=persisted_text,
                generated_file_ids=generated_file_ids,
                tool_calls_metadata=None,
                num_tokens_input=0,
                num_tokens_output=0,
                effective_prompt="",
                model_parameters_json={"mode": "speaker_mapping", "skipped": True},
                contract_validation=prepared.contract_validation,
                structured_output={"speakers": []},
                diagnostics=diagnostics,
                runtime_input_metadata=prepared.step_input.runtime_input_metadata,
                output_payload_extensions={
                    SPEAKER_MAPPING_PAYLOAD_KEY: {
                        "source_step_id": source_step_id,
                        "source_step_order": step.step_order - 1,
                        "source_attempt_no": source_attempt_no,
                        "participants_field": None,
                        "participants": [],
                        "inventory": [],
                        "skipped": True,
                    }
                },
            )
        )


def _upstream_diarization_skipped(step: RuntimeStep, state: RunExecutionState) -> bool:
    previous = state.completed_by_order.get(step.step_order - 1)
    payload = previous.input_payload_json if previous is not None else None
    transcription: object = (
        cast(dict[str, object], payload).get("transcription")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(transcription, dict):
        return False
    diarization: object = cast(dict[str, object], transcription).get("diarization")
    return isinstance(diarization, str) and diarization.startswith("skipped")


def _source_step_identity(
    step: RuntimeStep, state: RunExecutionState
) -> tuple[str | None, int | None]:
    previous = state.completed_by_order.get(step.step_order - 1)
    if previous is None:
        return None, None
    return str(previous.step_id), previous.current_attempt_no
