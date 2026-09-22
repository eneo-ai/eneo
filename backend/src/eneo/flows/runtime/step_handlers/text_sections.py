from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, cast

from eneo.completion_models.domain.request_preflight import CompletionRequestPackage
from eneo.flows.domain.flow import FlowRun, FlowStepResultStatus
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    build_step_material_aliases,
)
from eneo.flows.domain.text_processing import (
    SectionManifest,
    SectionRange,
    TextProcessingMode,
    TextSection,
    text_processing_config,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import merge_resolved_input_edges
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.step_deadline import require_step_budget
from eneo.flows.runtime.step_execution_runtime import (
    PreparedCompletionCall,
    build_prepared_completion_call,
    preview_step_execution_context,
)
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.flows.runtime.step_handlers.mapped_outputs import mapped_admission_payload
from eneo.flows.runtime.step_input_resolution import (
    finalize_step_input_question,
    resolve_default_step_input_text,
    resolve_step_input_binding,
)
from eneo.main.exceptions import TypedIOValidationException


@dataclass(frozen=True)
class PreparedTextSections:
    manifest: SectionManifest
    calls: tuple[PreparedAssistantStep, ...]


def _dispatchable_packages(
    completion: PreparedCompletionCall,
) -> tuple[CompletionRequestPackage, ...]:
    assert completion.preflight is not None
    return tuple(
        package
        for package in completion.preflight.packages
        if package is completion.selected_package
        or (
            package is completion.preflight.fallback
            and completion.capability_fallback_model_kwargs is not None
        )
    )


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for raw_part in cast(list[object], content):
            if isinstance(raw_part, dict):
                part = cast(dict[str, object], raw_part)
                text = part.get("text")
                if part.get("type") == "text" and isinstance(text, str):
                    text_parts.append(text)
        return "".join(text_parts)
    return ""


async def prepare_text_processing_call(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    base: PreparedAssistantStep,
    section_text: str,
    section_index: int = 1,
) -> tuple[PreparedAssistantStep, int]:
    step_input = base.prepared.step_input
    material = step_input.materials[0] if step_input.materials else None
    completion = base.prepared.completion_call
    if completion is None:
        raise RuntimeError("Text processing requires a packaged completion call.")
    require_step_budget(
        base.deps.deadline, step_order=step.step_order, phase="section preparation"
    )
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
        input_config=step.input_config,
        section_index=section_index,
        resolved_file_text=(
            {material.identity: section_text} if material is not None else {}
        ),
    )
    interpolation = base.deps.variable_resolver.interpolate_with_evidence(
        base.prepared.assistant.get_prompt_text(),
        context,
        binding_ref="assistant_prompt",
    )
    prompt = append_output_format_instructions(
        interpolation.text,
        resolve_format_spec(step.output_type).prompt_instructions(step.output_contract),
    )
    binding = resolve_step_input_binding(
        step=step,
        run=run,
        prior_results=state.prior_results,
        state=state,
        runtime_input_metadata=runtime_metadata,
        variable_resolver=base.deps.variable_resolver,
        resolved_file_text=(
            {material.identity: section_text} if material is not None else None
        ),
    )
    if binding is not None:
        question = binding.text
    else:
        _, question = resolve_default_step_input_text(
            step=step,
            run=run,
            prior_results=state.prior_results,
            state=state,
            source_text=step_input.source_text,
            runtime_input_text=section_text if material is None else None,
            resolved_file_text=(
                {material.identity: section_text} if material is not None else None
            ),
            logger=None,
        )
    question, structured = finalize_step_input_question(
        step=step,
        text=question,
        structured=binding.structured
        if binding is not None and binding.structured is not None
        else step_input.structured,
        binding=binding,
        prior_results=state.prior_results,
    )
    prepared = replace(
        base.prepared,
        effective_prompt=prompt,
        resolved_input_edges=merge_resolved_input_edges(
            tuple(
                edge
                for edge in base.prepared.resolved_input_edges
                if not edge.binding_ref.startswith("assistant_prompt:")
            ),
            interpolation.edges,
        ),
        step_input=replace(
            base.prepared.step_input,
            text=question,
            structured=structured,
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
    processing = text_processing_config(step.input_config)
    bound_output = (
        processing is not None
        and processing.mode == TextProcessingMode.PROCESS_EACH_SECTION
    )
    empty_completion: PreparedCompletionCall | None = None
    section_index = 1

    async def measure(start: int, end: int) -> tuple[PreparedAssistantStep, int]:
        call, estimate = await prepare_text_processing_call(
            step=step,
            run=run,
            state=state,
            base=base,
            section_text=text[start:end],
            section_index=section_index,
        )
        if bound_output and empty_completion is not None:
            candidate = call.prepared.completion_call
            assert candidate is not None and candidate.preflight is not None
            assert empty_completion.preflight is not None
            for package in _dispatchable_packages(candidate):
                empty_package = (
                    empty_completion.preflight.preferred
                    if package is candidate.preflight.preferred
                    else empty_completion.preflight.fallback
                )
                assert empty_package is not None
                # Conservative sizing leaves room for output proportional to material;
                # framing, reasoning and provider tokenization can still exceed it.
                material_tokens = (
                    package.input_reserve.tokens - empty_package.input_reserve.tokens
                )
                if (
                    not package.fits
                    or package.output_cap_tokens is None
                    or material_tokens > package.output_cap_tokens
                ):
                    raise TypedIOValidationException(
                        "Section material exceeds the request's available output capacity.",
                        code=FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value,
                    )
        return call, estimate

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
        section_index = len(sections) + 1
        if bound_output and sections:
            empty_completion = None
            empty_call, _ = await measure(0, 0)
            empty_completion = empty_call.prepared.completion_call
        low = start
        high = min(len(text), start + previous_size)
        # Token counts and package selection can change non-monotonically;
        # only measured fitting candidates may be retained.
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
            newline_index = text.rfind("\n", start + (end - start) // 2, end)
            whitespace_end = (
                newline_index + 1
                if newline_index >= 0
                else next(
                    (
                        index + 1
                        for index in range(end - 1, start - 1, -1)
                        if text[index].isspace()
                    ),
                    end,
                )
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
        prepared_completion = call.prepared.completion_call
        assert prepared_completion is not None
        core_text = text[start:end]
        for package in _dispatchable_packages(prepared_completion):
            if not any(
                core_text in _message_text(message) for message in package.messages
            ):
                raise TypedIOValidationException(
                    "Section processing requires the complete section text in every dispatched request.",
                    code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
                )
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
