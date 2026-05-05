TL;DR
- Live eval rerun used the localhost API and current branch implementation.
- C2 improved: applied C2 flows no longer used `all_previous_steps`.
- The deterministic fix targets non-terminal text composers before review/PDF renderers.
- C1 still fails builder repair in all runs and remains a separate blocker.
- N1 still overbuilds simple translation into 3-4 steps.

# T011 - Non-Terminal Targeted Underlag

## Problem

The C2 live case exposed a report-body text composer before review/PDF steps that still used `input_source="all_previous_steps"`. Earlier deterministic logic only inspected the last compositional text step, so non-terminal body composers could escape both the auto-binder and the critic.

## Change

The targeted-underlag predicate now evaluates every eligible compositional text step, not only the last one. The create-draft auto-binder and critic both use that shared predicate:

- `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py`
- `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py`

The auto-binder rewrites eligible non-terminal `all_previous_steps` composers to `previous_step` with explicit `uses_previous_fields` and source-preserving `uses_previous_outputs`. The critic now reports the same class of issue with index-agnostic wording.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py -q -k 'auto_bind_targeted_underlag or targeted_underlag or final_text_step_must_reference or nonterminal_body'`
  - `12 passed, 183 deselected`
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_dataflow.py src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
  - `All checks passed!`
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_dataflow.py src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
  - `4 files already formatted`
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_dataflow.py src/intric/flows/ai_builder/ai_builder_critic_invariants.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
  - `0 errors, 0 warnings, 0 informations`

## Claude Review

Claude peer loop session: `flow-ai-builder-material-efficiency-t011-live-rerun-next-slice`

- Iteration 1: blocked a vague next-slice plan and required a concrete failing test.
- Iteration 2: blocked disk/plan mismatch and required an explicit decision on critic-only versus auto-binder ownership.
- Iteration 3: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Artifact:

- `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260505T205554Z.md`

## Live Eval

Raw outputs remain outside git under `/tmp/material-efficiency-live-eval`.

- Targeted C2 rerun: `/tmp/material-efficiency-live-eval/20260505-225524-t011-c2-rerun/summary.json`
  - `C2`: `applied`
  - Applied flow: `f1ae7afb-114b-4de0-9ed8-2ff34f372ea0`
  - Observed `all_previous_steps_count`: `0`
  - PDF body composer included explicit structured fields from the document extraction and section steps, plus `organization_name` and `report_period`.
- Full create rerun: `/tmp/material-efficiency-live-eval/20260505-225658-t011-full-create-rerun/summary.json`
  - `V1`: `clarification_required` x3
  - `V2`: `applied` x3
  - `V3`: `clarification_required` x3
  - `V4`: `clarification_required` x3
  - `V5`: `clarification_required` x3
  - `C1`: `builder_error` x3
  - `C2`: `applied`, `applied`, `no_plan_after_requirements_confirmation`
  - `C3`: `applied` x3
  - `C4`: `clarification_required` x3
  - `C5`: `clarification_required` x3
  - Both applied C2 flows had `all_previous_steps_count=0`.
- Supplemental rerun: `/tmp/material-efficiency-live-eval/20260505-230611-t011-supplemental-rerun/summary.json`
  - `H1`: `clarification_required` x3
  - `H2`: `clarification_required` x3
  - `N1`: `applied` x3, but still overbuilt simple translation into 3-4 steps.
  - `Q1`: `no_plan`, `applied`, `applied`.

## Remaining Follow-Ups

- C1 remains a builder repair/planning blocker independent of this routing fix.
- C2 is materially improved, but one applied topology still routes some supporting material through later review steps instead of the body composer.
- N1 needs a restraint/minimal-topology slice so one-sentence translation does not produce a quality chain.
- The under-bind critic still evaluates the last compositional text step and uses a bounded suppression for body-composer-plus-review shapes; generalize it only when a red test proves a non-terminal `previous_step` composer drops structured priors.
