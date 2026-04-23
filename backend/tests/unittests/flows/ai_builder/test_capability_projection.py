"""Contract tests for the quality-first context projection module.

Pins the public contract of `ai_builder_capability_projection`:

- Pure function `build_llm_prompt_context(state, fcm, patterns)` that
  returns a frozen `LLMPromptContext` value object.
- Stage is derived from `PlanningState.architecture_commit`: `None`
  means `pre_commit`, otherwise `post_commit`.
- Pre-commit compression is mechanical only — every declared capability,
  signal, pattern, resolved slot, and open question survives.
- Post-commit compression narrows capabilities to
  `architecture_commit.required_capabilities`, patterns to
  `chosen_patterns`, drops signals already carried by `resolved_slots`,
  and drops any open questions (architecture is pinned).
- A CI sentinel marker lives verbatim on a line of its own in the
  module source. Removing it trips a review gate.
- Nested Pydantic models are deep-copied at projection time so
  post-call mutation of the source state cannot bleed into a
  previously returned context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    OpenQuestion,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY

MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "intric"
    / "flows"
    / "ai_builder"
    / "ai_builder_capability_projection.py"
)


def _empty_pre_commit_state() -> PlanningState:
    return PlanningState.empty()


def _committed_state(
    *,
    required_capabilities: list[str],
    chosen_patterns: list[str],
) -> PlanningState:
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=chosen_patterns,
        required_capabilities=required_capabilities,
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    return state


class TestModuleSurface:
    def test_module_imports(self) -> None:
        from intric.flows.ai_builder import (
            ai_builder_capability_projection as projection,
        )

        assert hasattr(projection, "build_llm_prompt_context")
        assert hasattr(projection, "LLMPromptContext")

    def test_module_carries_sentinel_tag(self) -> None:
        assert MODULE_PATH.exists(), (
            f"expected module at {MODULE_PATH}; the sentinel guard cannot "
            "grep a file that does not exist"
        )
        source = MODULE_PATH.read_text(encoding="utf-8")
        sentinel = "# quality-first-context: enforced"
        assert any(line.strip() == sentinel for line in source.splitlines()), (
            "module must carry the verbatim CI sentinel comment on a "
            "line of its own — removing it is a review-gate trip. "
            "Substring matches are not enough: the docstring references "
            "the sentinel verbatim, so only a standalone-line check "
            "catches deletion of the real marker."
        )


class TestPreCommitProjection:
    def test_stage_is_pre_commit_when_no_commit(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        ctx = build_llm_prompt_context(
            _empty_pre_commit_state(),
            CAPABILITY_REGISTRY,
            PATTERN_REGISTRY,
        )
        assert ctx.stage == "pre_commit"
        assert ctx.architecture_commit is None

    def test_pre_commit_preserves_every_builder_exposed_capability(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        ctx = build_llm_prompt_context(
            _empty_pre_commit_state(),
            CAPABILITY_REGISTRY,
            PATTERN_REGISTRY,
        )
        expected = {
            cap.id for cap in CAPABILITY_REGISTRY.values() if cap.exposure == "builder"
        }
        assert set(ctx.capabilities) == expected, (
            "pre-commit compression is mechanical only; every "
            "builder-exposed capability must survive"
        )

    def test_pre_commit_omits_not_exposed_capabilities(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        ctx = build_llm_prompt_context(
            _empty_pre_commit_state(),
            CAPABILITY_REGISTRY,
            PATTERN_REGISTRY,
        )
        assert "input_image" not in ctx.capabilities, (
            "INPUT_TYPE_POLICIES['image'].supported=False — the "
            "projection must never surface a not_exposed capability to "
            "the planner, even pre-commit"
        )

    def test_pre_commit_preserves_every_positive_pattern_id(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        ctx = build_llm_prompt_context(
            _empty_pre_commit_state(),
            CAPABILITY_REGISTRY,
            PATTERN_REGISTRY,
        )
        expected = {
            pattern.id
            for pattern in PATTERN_REGISTRY.values()
            if pattern.polarity == "positive"
        }
        assert set(ctx.pattern_ids) == expected

    def test_pre_commit_preserves_signals_verbatim(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        signal = PlanningSignal(
            question_id="final_output_mode",
            value="structured_text",
            confidence="high",
            source="structured_answer",
        )
        state = _empty_pre_commit_state()
        state.signals.append(signal)

        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert signal in ctx.signals, (
            "pre-commit may not drop a signal — the planner may still "
            "need it to commit architecture"
        )

    def test_pre_commit_preserves_open_questions(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        question = OpenQuestion(
            question_id="final_output_mode",
            slot_name="final_output_mode",
            priority=1,
            reason="output artefact undecided",
        )
        state = _empty_pre_commit_state()
        state.open_questions.append(question)

        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert question in ctx.open_questions

    def test_pre_commit_carries_every_exposed_invariant(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        ctx = build_llm_prompt_context(
            _empty_pre_commit_state(),
            CAPABILITY_REGISTRY,
            PATTERN_REGISTRY,
        )
        expected_pairs = {
            (cap.id, inv.id)
            for cap in CAPABILITY_REGISTRY.values()
            if cap.exposure == "builder"
            for inv in cap.invariants
        }
        assert set(ctx.critic_invariants) == expected_pairs


class TestPostCommitProjection:
    def test_stage_is_post_commit_when_commit_present(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert ctx.stage == "post_commit"
        # Equality — not identity. Snapshot semantics guarantee the
        # projection holds a deep copy, not the source reference, so
        # later in-place mutation of `state.architecture_commit`
        # cannot leak into this context.
        assert ctx.architecture_commit == state.architecture_commit
        assert ctx.architecture_commit is not state.architecture_commit

    def test_post_commit_narrows_to_required_capabilities(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert set(ctx.capabilities) == {
            "input_text",
            "output_mode_pass_through",
        }

    def test_post_commit_narrows_patterns_to_chosen(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert tuple(ctx.pattern_ids) == ("summarize_text",)

    def test_post_commit_drops_open_questions(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        state.open_questions.append(
            OpenQuestion(
                question_id="final_output_mode",
                slot_name="final_output_mode",
                priority=1,
                reason="stale after commit",
            )
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert ctx.open_questions == (), (
            "architecture is pinned; any outstanding question is stale "
            "and must not inflate the post-commit prompt"
        )

    def test_post_commit_drops_signals_already_resolved_as_slots(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        resolved = ResolvedSlot(
            name="final_output_mode",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        )
        state.resolved_slots[resolved.name] = resolved
        state.signals.append(
            PlanningSignal(
                question_id="final_output_mode",
                value="structured_text",
                confidence="high",
                source="structured_answer",
            )
        )
        state.signals.append(
            PlanningSignal(
                question_id="input_material_mode",
                value="text",
                confidence="high",
                source="structured_answer",
            )
        )

        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        surviving_qids = {signal.question_id for signal in ctx.signals}
        assert "final_output_mode" not in surviving_qids, (
            "post-commit: the resolved slot is the authoritative carry "
            "for a resolved question; the signal is redundant"
        )
        assert "input_material_mode" in surviving_qids, (
            "post-commit does not strip signals that were not yet lifted "
            "into a resolved slot"
        )

    def test_post_commit_invariants_narrow_to_required_capabilities(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["output_mode_template_fill"],
            chosen_patterns=["document_to_docx_template"],
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        surviving_cap_ids = {cap_id for cap_id, _ in ctx.critic_invariants}
        assert surviving_cap_ids == {"output_mode_template_fill"}, (
            "critic invariants must narrow along with the capability "
            "set; unrelated invariants are noise after commit"
        )


class TestDeterminism:
    def test_projection_is_deterministic(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _empty_pre_commit_state()
        first = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        second = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert first == second, "projection must be order-stable across calls"

    def test_capabilities_and_patterns_are_sorted(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        ctx = build_llm_prompt_context(
            _empty_pre_commit_state(),
            CAPABILITY_REGISTRY,
            PATTERN_REGISTRY,
        )
        assert list(ctx.capabilities) == sorted(ctx.capabilities)
        assert list(ctx.pattern_ids) == sorted(ctx.pattern_ids)


class TestResolvedSlots:
    """The contract pins slot survival in both stages — add direct
    coverage. Pre-commit: slots survive verbatim. Post-commit: slots
    survive; the signal→slot override is tested separately."""

    def _build_state_with_out_of_order_slots(self, *, commit: bool) -> PlanningState:
        state = (
            _committed_state(
                required_capabilities=["input_text", "output_mode_pass_through"],
                chosen_patterns=["summarize_text"],
            )
            if commit
            else _empty_pre_commit_state()
        )
        for name in ("zeta_slot", "alpha_slot", "mu_slot"):
            state.resolved_slots[name] = ResolvedSlot(
                name=name,
                value=f"{name}-value",
                source="structured_answer",
                confidence="high",
            )
        return state

    def test_pre_commit_preserves_resolved_slots_in_name_order(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = self._build_state_with_out_of_order_slots(commit=False)
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert tuple(slot.name for slot in ctx.resolved_slots) == (
            "alpha_slot",
            "mu_slot",
            "zeta_slot",
        )

    def test_post_commit_preserves_resolved_slots_in_name_order(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = self._build_state_with_out_of_order_slots(commit=True)
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        assert tuple(slot.name for slot in ctx.resolved_slots) == (
            "alpha_slot",
            "mu_slot",
            "zeta_slot",
        )


class TestSnapshotSafety:
    """Post-call mutation of the source `PlanningState` must not
    bleed into a previously-returned context — that is the weaker
    contract the module took on when it dropped the hashability
    claim in favor of deep-copy semantics."""

    def test_context_is_not_hashable(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _empty_pre_commit_state()
        state.signals.append(
            PlanningSignal(
                question_id="final_output_mode",
                value="structured_text",
                confidence="high",
                source="structured_answer",
            )
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)
        with pytest.raises(TypeError):
            # Pydantic models inside the tuple are not frozen, so the
            # projection is deliberately non-hashable. Caller-side
            # caching must derive a key from `.model_dump()` or a
            # similar explicit snapshot.
            hash(ctx)

    def test_mutating_signal_after_projection_does_not_bleed(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _empty_pre_commit_state()
        signal = PlanningSignal(
            question_id="final_output_mode",
            value="structured_text",
            confidence="high",
            source="structured_answer",
        )
        state.signals.append(signal)
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)

        signal.value = "mutated_after_projection"

        assert ctx.signals[0].value == "structured_text", (
            "post-call mutation of the source PlanningSignal must not "
            "propagate into a previously returned context — the "
            "projection carries deep copies"
        )

    def test_mutating_commit_after_projection_does_not_bleed(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        ctx = build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)

        original_commit = state.architecture_commit
        assert original_commit is not None
        original_patterns = list(original_commit.chosen_patterns)
        original_commit.chosen_patterns.append("stale_injected_pattern")

        ctx_commit = ctx.architecture_commit
        assert ctx_commit is not None
        assert list(ctx_commit.chosen_patterns) == original_patterns


class TestPurity:
    def test_does_not_mutate_input_state(self) -> None:
        from intric.flows.ai_builder.ai_builder_capability_projection import (
            build_llm_prompt_context,
        )

        state = _committed_state(
            required_capabilities=["input_text", "output_mode_pass_through"],
            chosen_patterns=["summarize_text"],
        )
        state.signals.append(
            PlanningSignal(
                question_id="final_output_mode",
                value="structured_text",
                confidence="high",
                source="structured_answer",
            )
        )
        signals_before = list(state.signals)
        slots_before = dict(state.resolved_slots)
        questions_before = list(state.open_questions)

        build_llm_prompt_context(state, CAPABILITY_REGISTRY, PATTERN_REGISTRY)

        assert list(state.signals) == signals_before
        assert dict(state.resolved_slots) == slots_before
        assert list(state.open_questions) == questions_before


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-x", "-v"])
