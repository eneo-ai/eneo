"""Builders for the measured suggestion tests: draft steps, the content-free
run evidence the measured rules read, and a filter by code."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from eneo.flows.domain.flow_suggestion_evidence import (
    EvidenceAttempt,
    EvidenceCall,
    EvidenceEdge,
    EvidenceRun,
    RunEvidence,
    StepDefinitionFacts,
)
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    SuggestionFlow,
    SuggestionStep,
    analyze_flow,
)
from eneo.flows.domain.forwarding_facts import ForwardingFacts
from eneo.flows.enums import FlowInputSource, FlowOutputMode

IDS = [UUID(int=index) for index in range(1, 20)]
MODEL = UUID(int=900)
PROMPT_READ = "assistant_prompt:step_1.output.text"


def make_step(
    order: int,
    *,
    prompt_text: str | None = "Gör uppgiften.",
    output_mode: FlowOutputMode = FlowOutputMode.PASS_THROUGH,
    input_source: FlowInputSource = FlowInputSource.PREVIOUS_STEP,
    output_type: str = "text",
    output_contract: Mapping[str, object] | None = None,
    step_id: UUID | None = None,
) -> SuggestionStep:
    return SuggestionStep(
        id=step_id or IDS[order],
        step_order=order,
        user_description=f"Steg {order}",
        input_source=FlowInputSource.FLOW_INPUT if order == 1 else input_source,
        input_type="text",
        input_bindings=None,
        input_config=None,
        output_mode=output_mode,
        output_type=output_type,
        output_contract=output_contract,
        output_config=None,
        prompt_text=prompt_text,
        assistant_id=uuid4(),
    )


def make_edge(
    ref: str, producer: int, *, size: int = 1000, sha: str = "a"
) -> EvidenceEdge:
    return EvidenceEdge(
        binding_ref=ref,
        source_step_id=IDS[producer],
        selector=("output", "text"),
        byte_size=size,
        sha256=sha * 64,
    )


def make_call(
    tokens: int | None,
    indexes: Sequence[int],
    *,
    reason: str = "initial",
    output: int | None = 50,
    status: str = "completed",
) -> EvidenceCall:
    return EvidenceCall(
        status=status,
        call_reason=reason,
        num_tokens_input=tokens,
        num_tokens_output=output if tokens is not None else None,
        edge_indexes=tuple(indexes),
    )


def make_attempt(
    order: int,
    edges: Sequence[EvidenceEdge] = (),
    calls: Sequence[EvidenceCall] = (),
    *,
    status: str = "completed",
    error_code: str | None = None,
    forwarding: ForwardingFacts | None = None,
) -> EvidenceAttempt:
    return EvidenceAttempt(
        step_id=IDS[order],
        step_order=order,
        status=status,
        error_code=error_code,
        edges=tuple(edges),
        calls=tuple(calls),
        forwarding=forwarding,
    )


def make_facts(
    *,
    model: UUID | None = MODEL,
    definition: str = "same",
    output_type: str = "text",
    reasoning_effort: str | None = None,
) -> StepDefinitionFacts:
    return StepDefinitionFacts(
        definition_hash=definition,
        completion_model_id=model,
        output_type=output_type,
        reasoning_effort=reasoning_effort,
    )


def make_evidence(
    steps: Sequence[SuggestionStep],
    runs: Sequence[Sequence[EvidenceAttempt]],
    *,
    version: int = 3,
    limit: int | None = None,
    published: Mapping[UUID, StepDefinitionFacts] | None = None,
    draft: Mapping[UUID, StepDefinitionFacts] | None = None,
    reasoning_models: frozenset[UUID] = frozenset(),
) -> RunEvidence:
    """``runs`` newest first, all of ``version``. Each draft step has
    ``make_facts()`` unless ``draft`` says otherwise, and has its draft facts
    in the version unless ``published`` says otherwise."""
    draft_facts = {step.id: make_facts() for step in steps} | dict(draft or {})
    return RunEvidence(
        runs=tuple(
            EvidenceRun(run_id=uuid4(), version=version, attempts=tuple(attempts))
            for attempts in runs
        ),
        published_steps={
            (version, step_id): facts
            for step_id, facts in (draft_facts | dict(published or {})).items()
        },
        draft_steps=draft_facts,
        model_input_limits={MODEL: limit} if limit is not None else {},
        reasoning_models=reasoning_models,
    )


def of_code(
    suggestions: Sequence[FlowSuggestion], code: FlowSuggestionCode
) -> list[FlowSuggestion]:
    return [item for item in suggestions if item.code is code]


def analyzed(
    steps: Sequence[SuggestionStep],
    runs: Sequence[Sequence[EvidenceAttempt]],
    code: FlowSuggestionCode,
    **kwargs: Any,
) -> list[FlowSuggestion]:
    """The suggestions of ``code`` the draft gets measured over ``runs``."""
    return of_code(
        analyze_flow(SuggestionFlow(steps=steps), make_evidence(steps, runs, **kwargs)),
        code,
    )
