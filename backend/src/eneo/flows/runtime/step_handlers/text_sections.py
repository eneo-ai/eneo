from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from eneo.flows.domain.flow import FlowRun, FlowStepResultStatus
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    build_step_material_aliases,
)
from eneo.flows.domain.text_processing import SectionManifest, SectionRange, TextSection
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.step_deadline import require_step_budget
from eneo.flows.runtime.step_execution_runtime import (
    build_prepared_completion_call,
    preview_step_execution_context,
)
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.flows.runtime.step_handlers.mapped_outputs import mapped_admission_payload
from eneo.flows.runtime.step_input_resolution import resolve_default_step_input_text
from eneo.main.exceptions import TypedIOValidationException


@dataclass(frozen=True)
class PreparedTextSections:
    manifest: SectionManifest
    calls: tuple[PreparedAssistantStep, ...]


async def prepare_text_sections(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    base: PreparedAssistantStep,
    policy: FlowMappedExecutionPolicy,
) -> PreparedTextSections:
    step_input = base.prepared.step_input
    materials = step_input.materials
    files = step_input.files or []
    if len(materials) + len(files) != 1:
        raise TypedIOValidationException(
            "Section processing requires exactly one material.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    material = materials[0] if materials else None
    text = material.text if material is not None else files[0].text
    if not text:
        raise TypedIOValidationException(
            "Section processing requires readable text.",
            code=FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION.value,
        )
    sources = (
        build_step_material_aliases(
            materials=materials,
            max_inline_bytes=base.deps.max_inline_text_bytes,
        )
        if material is not None
        else (
            FileBackedStepText(
                preview="",
                inline_text_bytes=0,
                full_text_bytes=len(text.encode("utf-8")),
                file_id=files[0].id,
                checksum=files[0].checksum,
            ),
        )
    )
    completion = base.prepared.completion_call
    if completion is None:
        raise RuntimeError("Section processing requires a packaged completion call.")
    question_template = effective_question_binding(step.input_bindings)

    async def measure(start: int, end: int) -> tuple[PreparedAssistantStep, int]:
        require_step_budget(
            base.deps.deadline, step_order=step.step_order, phase="section preparation"
        )
        section_text = text[start:end]
        runtime_metadata = step_input.runtime_input_metadata
        if material is None and runtime_metadata is not None:
            runtime_metadata = {
                **runtime_metadata,
                "text": section_text,
                "extracted_text_length": len(section_text),
            }
        context = base.deps.variable_resolver.build_context_with_evidence(
            run.input_payload_json,
            [
                result
                for result in state.prior_results
                if result.status == FlowStepResultStatus.COMPLETED
            ],
            current_step_order=step.step_order,
            step_names_by_order=state.step_names_by_order,
            step_ref_mapping=state.step_ref_mapping,
            current_step_input=runtime_metadata,
            resolved_step_text=(
                {material.source_step_id: section_text} if material is not None else {}
            ),
        )
        interpolation = base.deps.variable_resolver.interpolate_with_evidence(
            base.prepared.assistant.get_prompt_text(),
            context,
            binding_ref="assistant_prompt",
        )
        prompt = append_output_format_instructions(
            interpolation.text,
            resolve_format_spec(step.output_type).prompt_instructions(
                step.output_contract
            ),
        )
        if question_template is not None:
            question = base.deps.variable_resolver.interpolate_with_evidence(
                question_template, context, binding_ref="input_bindings.question"
            ).text
        else:
            _, question = resolve_default_step_input_text(
                step=step,
                run=run,
                prior_results=state.prior_results,
                state=state,
                source_text=step_input.source_text,
                runtime_input_text=section_text if material is None else None,
                resolved_step_text=(
                    {material.source_step_id: section_text}
                    if material is not None
                    else None
                ),
                logger=None,
            )
        prepared = replace(
            base.prepared,
            effective_prompt=prompt,
            step_input=replace(
                base.prepared.step_input,
                text=question,
                source_text=section_text,
                raw_extracted_text=section_text,
            ),
            llm_files=None,
            completion_call=None,
        )
        prepared.completion_call = build_prepared_completion_call(
            step=step,
            state=state,
            prepared=prepared,
            useful_output_reserve_tokens=completion.useful_output_reserve_tokens,
        )
        estimate = await preview_step_execution_context(
            step=step,
            state=state,
            prepared=prepared,
            deps=replace(base.deps, logger=None),
        )
        return PreparedAssistantStep(prepared=prepared, deps=base.deps), estimate

    # Prove that the prompt, schema and output reserve fit before splitting text.
    empty_call, _ = await measure(0, 0)
    empty_completion = empty_call.prepared.completion_call
    assert empty_completion is not None
    assert empty_completion.preflight is not None
    assert empty_completion.selected_package is not None
    section_budget = (
        empty_completion.preflight.capacity.input_allowance(
            output_reserve_tokens=completion.useful_output_reserve_tokens,
            safety_tokens=0,
        )
        - empty_completion.selected_package.input_reserve.tokens
    )
    calls: list[PreparedAssistantStep] = []
    sections: list[TextSection] = []
    estimates: list[int] = []
    start = 0
    previous_size = max(1, section_budget)
    while start < len(text):
        low = start
        high = min(len(text), start + previous_size)
        best: tuple[PreparedAssistantStep, int] | None = None
        while True:
            try:
                candidate = await measure(start, high)
            except TypedIOValidationException as exc:
                if (
                    exc.code
                    != FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value
                ):
                    raise
                break
            low, best = high, candidate
            if high == len(text):
                break
            high = min(len(text), start + (high - start) * 2)
        while high - low > 1:
            middle = (low + high) // 2
            try:
                candidate = await measure(start, middle)
            except TypedIOValidationException as exc:
                if (
                    exc.code
                    != FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value
                ):
                    raise
                high = middle
            else:
                low, best = middle, candidate
        if best is None:
            # Preserve the preflight's typed refusal when even one character cannot fit.
            await measure(start, start + 1)
            raise RuntimeError("Section preflight did not produce a fitting package.")
        end = low
        if end < len(text):
            whitespace_end = next(
                (
                    index + 1
                    for index in range(end - 1, start - 1, -1)
                    if text[index].isspace()
                ),
                end,
            )
            if whitespace_end != end:
                try:
                    candidate = await measure(start, whitespace_end)
                except TypedIOValidationException as exc:
                    if (
                        exc.code
                        != FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value
                    ):
                        raise
                else:
                    end, best = whitespace_end, candidate
        call, estimate = best
        calls.append(call)
        estimates.append(estimate)
        sections.append(
            TextSection(
                core=SectionRange(start_char=start, end_char=end),
                output_index=len(sections),
            )
        )
        state.mapped_admission_by_step[step.step_id] = mapped_admission_payload(
            execution_mode="per_item",
            estimates=estimates,
            native_json_fallback_possible=completion.capability_fallback_model_kwargs
            is not None,
            policy=policy,
        )
        previous_size = end - start
        start = end

    content = text.encode("utf-8")
    manifest = SectionManifest(
        content_sha256=sha256(content).hexdigest(),
        utf8_length=len(content),
        character_length=len(text),
        sources=sources,
        sections=tuple(sections),
    )
    if manifest.resplit(text) != tuple(
        call.prepared.step_input.source_text for call in calls
    ):
        raise ValueError(
            "Section manifest differs from the measured completion inputs."
        )
    return PreparedTextSections(manifest=manifest, calls=tuple(calls))
