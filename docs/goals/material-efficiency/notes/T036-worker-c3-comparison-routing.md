# T036 Worker Receipt: High-Confidence Comparison Routing

## Result

Narrow deterministic improvement ready for commit; broader live-builder
instability remains out of scope for this slice.

## Problem

C3-style multi-source comparison prompts were detected as document input and
structured analysis, but not as multi-document comparison architecture. The
planner could then compile a shallow linear chain even when the user explicitly
asked for source-to-source contradiction analysis with broad fan-in.

## Change

- Added generic multi-source file evidence and high-confidence source-to-source
  comparison evidence in `ai_builder_discovery_signal_inference.py`.
- Replaced the blanket freeform `comparison_scope` suppression in
  `extract_answer_signals` with a high-confidence gate, so ambiguous comparison
  prompts still ask the discovery question.
- Added `comparison_scope` materialization to `planning_state_builder.py` using
  the existing `_single_slot_value` / `_build_slot` path, with no policy default.
- Added behavior tests for direct predicate behavior, signal extraction,
  requirements-summary ordering, discovery restraint, planning-state slot
  materialization, and architecture compare intent.

## Red Evidence

The scoped test run failed before the production fix:

- missing public high-confidence predicate import;
- C3-style prompt still asked `comparison_scope`;
- C3-style planning state resolved `document_material_scope` as
  `flexible_document_case`;
- `comparison_scope` was missing from `PlanningState.resolved_slots`;
- architecture derivation did not reach `aggregation_intent=compare`.

Command:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_architecture_derivation.py -q
```

## Verification

- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_architecture_derivation.py -q`
  - `173 passed`
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q`
  - `2047 passed, 4 skipped`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_discovery_signal_inference.py src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_architecture_derivation.py`
  - `0 errors, 0 warnings, 0 informations`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_discovery_signal_inference.py src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_architecture_derivation.py`
  - `All checks passed`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_discovery_signal_inference.py src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_architecture_derivation.py`
  - `7 files already formatted`

## Live Eval

Targeted C3 eval:

- Summary: `/tmp/material-efficiency-live-eval/20260506-064611-t036-c3-comparison-routing/summary.json`
- Result: C3 applied `3/3`.
- Automated metrics: each run had `all_previous_steps_count=1`, improving the
  previous observed C3 topology where applied runs had `all_previous_steps_count=0`.
- Generated plans now include a compare/aggregate `all_previous_steps` terminal
  step instead of an entirely linear previous-step chain.

User-requested rerun after the same working-tree changes:

- Full create summary:
  `/tmp/material-efficiency-live-eval/20260506-063602-user-rerun-full-create-3run-apply-publish/summary.json`
- Smoke summary:
  `/tmp/material-efficiency-live-eval/20260506-063542-user-rerun-smoke-2/summary.json`
- Supplemental summary:
  `/tmp/material-efficiency-live-eval/20260506-065419-user-rerun-supplemental-n1-q1-h1-h2/summary.json`
- C3 result: C3 applied `2/3`; the failed run returned
  `self_correction_invalid_plan: Plan still invalid after correction.`
- C3 applied-flow metrics: each successful C3 run had
  `all_previous_steps_count=1`. This is an improvement over the earlier fully
  linear C3 topology, but it is not the final bounded-routing target.
- V2 result: `no_plan`, `no_plan`, `applied`, indicating a separate
  stream/session or planner-finalization flake for audio-to-DOCX creation.
- E1 edit-path result against an unpublished C1 flow:
  `/tmp/material-efficiency-live-eval/20260506-065957-user-rerun-e1-edit-unpublished-c1/summary.json`
  failed `3/3` with HTTP 500 during apply (`error_id`s `c56cc3cf`,
  `56564ec1`, `30813d7c`). The generated edit plans preserved material metrics,
  so this is tracked as an edit-apply/runtime issue, not fixed by T036.

Broader one-pass create regression suite:

- Summary: `/tmp/material-efficiency-live-eval/20260506-065049-t036-create-suite-regression/summary.json`
- Result: V2, C1, C3, and C5 applied; V1, V3, V4, V5, and C4 remained
  clarification-required; C2 hit a builder error.
- C2 follow-up: `/tmp/material-efficiency-live-eval/20260506-065712-t036-c2-regression-check/summary.json`
  reproduced `self_correction_invalid_plan` twice. A deterministic probe shows
  the C2 prompt still resolves `document_material_scope=single_document_case`
  and no `comparison_scope`, so this appears separate from the
  comparison-routing gate.
- Claude commit gate:
  `.codex/artifacts/claude-peer-loop-t036-implementation-review-20260506T051036Z.md`
  returned `GREEN_LIGHT: yes` with `MIN_SCORE: 8`. The post-Claude probe above
  closed its only material verification gap.

## Follow-Up Triggers

- Before the next compare-routing slice, evaluate a typed `ComparisonEvidence`
  owner on `DiscoveryProfile` so comparison confidence is not split between
  signal inference, framework gating, and planning-state materialization.
- Before the next slot-addition slice, evaluate collapsing
  `planning_state_builder.py` scalar-slot blocks into a list-driven resolver.
