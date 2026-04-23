"""Quality-first context projection for the AI Builder planner.

The projection is the single cut point where the planner's prompt
surface is compressed. Every planner turn assembles its system prompt
from a deterministic, typed `LLMPromptContext` that narrows the FCM +
Pattern Registry + PlanningState down to the subset the LLM needs for
the current stage.

Stage is derived from `PlanningState.architecture_commit`:

- `None` → `"pre_commit"`. Compression is **mechanical only**: every
  builder-exposed FCM capability, every positive pattern, every signal,
  every resolved slot, every open question, and every exposed-capability
  invariant survives. Dropping anything load-bearing pre-commit is the
  exact regression that forced the rewrite, so this stage deliberately
  loses no planner-useful information.

- non-`None` → `"post_commit"`. Compression is looser: capabilities
  narrow to `ArchitectureCommit.required_capabilities`, patterns narrow
  to `ArchitectureCommit.chosen_patterns`, invariants narrow to those
  capabilities only, signals drop any entry whose `question_id` already
  appears as a key in `PlanningState.resolved_slots` (the slot is the
  authoritative carry), and open questions are dropped entirely (the
  architecture is pinned).

The module carries a verbatim CI sentinel comment on a line of its own
(see the line immediately after this docstring). Removing the sentinel
trips a review gate.

Pure function, no I/O. Nested Pydantic models (`PlanningSignal`,
`ResolvedSlot`, `OpenQuestion`, `ArchitectureCommit`) are deep-copied
at projection time, so post-call mutation of the source state does
not bleed through into the projection. The output supports equality
comparison and `model_dump`-based cache-key derivation, but it is NOT
hashable — several nested Pydantic models are mutable and treating the
projection as a dict key or set member would silently misbehave.
"""

# quality-first-context: enforced

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from intric.flows.ai_builder.pattern_registry import Pattern
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    OpenQuestion,
    PlanningPhase,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
)
from intric.flows.flow_capability_manifest import FlowCapability

ProjectionStage = Literal["pre_commit", "post_commit"]


@dataclass(frozen=True, slots=True)
class LLMPromptContext:
    """Stage-compressed projection of planner-visible state.

    Field ordering is chosen for reader ergonomics (scalar version
    stamps first, then selections, then state). Tuples are sorted for
    determinism so two calls with equal inputs produce equal outputs —
    a load-bearing property for any future caching or caller-side
    hashing.
    """

    stage: ProjectionStage
    planning_phase: PlanningPhase
    fcm_version: int
    planner_contract_version: int
    builder_schema_version: int
    capabilities: tuple[str, ...]
    pattern_ids: tuple[str, ...]
    critic_invariants: tuple[tuple[str, str], ...]
    signals: tuple[PlanningSignal, ...]
    resolved_slots: tuple[ResolvedSlot, ...]
    open_questions: tuple[OpenQuestion, ...]
    architecture_commit: ArchitectureCommit | None


def build_llm_prompt_context(
    state: PlanningState,
    fcm: Mapping[str, FlowCapability],
    patterns: Mapping[str, Pattern],
) -> LLMPromptContext:
    """Project PlanningState + FCM + Pattern Registry into a prompt context.

    Pure. Inputs are treated read-only and every nested Pydantic model
    placed on the returned context is `model_copy(deep=True)`-ed so
    the caller cannot bleed in-place state mutations into a prior
    projection. See module docstring for the stage-dependent
    compression contract.
    """
    commit = state.architecture_commit
    stage: ProjectionStage = "pre_commit" if commit is None else "post_commit"

    if stage == "pre_commit":
        capability_ids = _pre_commit_capability_ids(fcm)
        pattern_ids = _pre_commit_pattern_ids(patterns)
        invariants = _invariants_for(fcm, capability_ids)
        selected_signals: list[PlanningSignal] = list(state.signals)
        selected_open_questions: list[OpenQuestion] = list(state.open_questions)
    else:
        assert commit is not None  # narrowed by the stage branch
        capability_ids = _post_commit_capability_ids(fcm, commit)
        pattern_ids = _post_commit_pattern_ids(patterns, commit)
        invariants = _invariants_for(fcm, capability_ids)
        selected_signals = [
            signal
            for signal in state.signals
            if signal.question_id not in state.resolved_slots
        ]
        selected_open_questions = []

    signals_snapshot = tuple(
        signal.model_copy(deep=True) for signal in selected_signals
    )
    open_questions_snapshot = tuple(
        question.model_copy(deep=True) for question in selected_open_questions
    )
    resolved_slots_snapshot = tuple(
        state.resolved_slots[name].model_copy(deep=True)
        for name in sorted(state.resolved_slots)
    )
    commit_snapshot = commit.model_copy(deep=True) if commit is not None else None

    return LLMPromptContext(
        stage=stage,
        planning_phase=state.phase,
        fcm_version=state.fcm_version,
        planner_contract_version=state.planner_contract_version,
        builder_schema_version=state.builder_schema_version,
        capabilities=capability_ids,
        pattern_ids=pattern_ids,
        critic_invariants=invariants,
        signals=signals_snapshot,
        resolved_slots=resolved_slots_snapshot,
        open_questions=open_questions_snapshot,
        architecture_commit=commit_snapshot,
    )


def _pre_commit_capability_ids(
    fcm: Mapping[str, FlowCapability],
) -> tuple[str, ...]:
    return tuple(sorted(cap.id for cap in fcm.values() if cap.exposure == "builder"))


def _post_commit_capability_ids(
    fcm: Mapping[str, FlowCapability],
    commit: ArchitectureCommit,
) -> tuple[str, ...]:
    # Silently ignore any committed capability the FCM no longer carries
    # — the commit is authoritative for what the planner must honor,
    # but the FCM is authoritative for what can be rendered. A drift
    # here surfaces at orchestrator-level validation, not in the
    # projection.
    allowed = {cap.id for cap in fcm.values() if cap.exposure == "builder"}
    return tuple(
        sorted(cap_id for cap_id in commit.required_capabilities if cap_id in allowed)
    )


def _pre_commit_pattern_ids(patterns: Mapping[str, Pattern]) -> tuple[str, ...]:
    return tuple(
        sorted(
            pattern.id
            for pattern in patterns.values()
            if pattern.polarity == "positive"
        )
    )


def _post_commit_pattern_ids(
    patterns: Mapping[str, Pattern],
    commit: ArchitectureCommit,
) -> tuple[str, ...]:
    # Same drift-tolerant policy as capabilities: a chosen pattern no
    # longer in the registry is not rendered here.
    return tuple(sorted(pid for pid in commit.chosen_patterns if pid in patterns))


def _invariants_for(
    fcm: Mapping[str, FlowCapability],
    capability_ids: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for cap_id in capability_ids:
        cap = fcm.get(cap_id)
        if cap is None:
            continue
        for invariant in cap.invariants:
            pairs.append((cap.id, invariant.id))
    return tuple(sorted(pairs))


__all__ = [
    "LLMPromptContext",
    "ProjectionStage",
    "build_llm_prompt_context",
]
