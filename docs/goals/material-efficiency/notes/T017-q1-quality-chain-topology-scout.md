# T017 Q1 Quality-Chain Topology Scout

## Problem

The latest credentialed T015 live run showed Q1 applied 3/3, but one run
added a redundant formatting pair after the requested quality chain:

- `Q1-run1`: 3 LLM steps.
- `Q1-run2`: 3 LLM steps.
- `Q1-run3`: 5 LLM steps, adding:
  - `Formatera som strukturerat textresultat` (`text -> json`)
  - `Skapa slutresultat` (`json -> text`)

The Q1 prompt already asks for the full topology: create a short answer, run a
separate critique step for clarity/factuality, then write a final version using
the critique. The extra JSON/text tail increases context and latency without
adding requested behavior.

Live artifact evidence:

- `/tmp/material-efficiency-live-eval/20260506-011206-t015-boundary-marker-targeted/Q1-run1/plan.json`
- `/tmp/material-efficiency-live-eval/20260506-011206-t015-boundary-marker-targeted/Q1-run2/plan.json`
- `/tmp/material-efficiency-live-eval/20260506-011206-t015-boundary-marker-targeted/Q1-run3/plan.json`

## Canonical Owner

The likely canonical owner is
`backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py`.

Evidence:

- `ai_builder_critic_invariants.py:688-722` owns the direct text-transform
  restraint invariant and its one-step shape.
- `test_ai_builder_plan_quality_critic.py:706-741` already protects the
  important non-goal: explicit quality chains must not be collapsed to one step.
- `ai_builder_critic_invariants.py:1065-1163` owns a related topology/material
  invariant for final text composers over structured JSON underlag.
- `ai_builder_planner_pattern_signals.py:216-263` only detects planner-pattern
  signals; it should not own final topology validation.

The registry/skeleton owner is not the right first target. Q1 is not a compiled
document-quality pattern; it is a plain text flow where the LLM proposal already
emits the full plan. The missing guard is a critic invariant over the proposed
spec, not a skeleton materializer.

## Deterministic Reproducer

I constructed two `FlowDraftSpecCore` values matching the live shapes and passed
them through `build_conversation_aware_quality_feedback`:

- Desired 3-step shape:
  - text draft
  - JSON critique
  - final text revision
  - Result: `None`, correct.
- Redundant 5-step shape:
  - text draft
  - JSON critique
  - final text revision
  - JSON formatting wrapper
  - final text wrapper
  - Result: `None`, incorrect.

Command:

```bash
uv run --directory backend python - <<'PY'
from intric.flows.ai_builder.ai_builder_plan_quality_critic import build_conversation_aware_quality_feedback
...
PY
```

Output:

```text
good None
bad None
```

This proves the gap can be covered deterministically without live API access.

## Proposed Worker Slice

Objective:

Add a topology-only critic invariant that rejects an unrequested terminal
JSON-format tail after an already-final text composer. The rule must read the
`FlowDraftSpecCore` shape, not Q1 wording or quality-chain prompt markers, and
must preserve explicit user-requested JSON, artifacts, form fields, document
workflows, and the valid three-step text -> JSON critique -> text revision
shape.

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
- `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`
- `docs/goals/material-efficiency/notes/T017-q1-quality-chain-topology-scout.md`
- `docs/goals/material-efficiency/notes/T018-q1-quality-chain-topology.md`

Candidate red tests:

- A 5-step text -> JSON -> text -> JSON -> text proposal should get a semantic
  quality feedback issue when the final text composer already produced the
  requested text result before the JSON tail.
- A 4-step text -> JSON -> text -> JSON proposal should get the same issue when
  the JSON tail is terminal.
- A 3-step text -> JSON -> text quality chain should remain accepted.
- A prompt explicitly asking for JSON output should not trigger this invariant.
- A document/PDF/DOCX terminal flow should not trigger this invariant.
- A form-field-driven JSON terminal/wrapper should not trigger this invariant.
- Edit-context plans should be covered without relying on fresh prompt wording.

Verification:

- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py -q -k 'quality_chain or redundant_terminal'`
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py -q`
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`

Stop if:

- The fix requires Q1-specific Swedish wording.
- The rule depends on conversation keywords instead of `StepSpec` topology.
- The invariant would collapse explicit quality-chain prompts to one step.
- The invariant would reject explicit JSON terminal output.
- The implementation touches blocked T016 source files, unrelated dirty files,
  or `scripts/run_codex_review.sh`.
- The implementation needs files outside the allowed set.
