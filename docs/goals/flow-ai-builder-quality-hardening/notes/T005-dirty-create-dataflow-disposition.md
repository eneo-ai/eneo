# T005 Dirty Create/Dataflow Disposition

## Summary

The current worktree contains useful AI Builder quality-hardening work, but it
must not be staged as one draft. The safe next step is a Judge-selected Worker
slice that isolates create-mode dataflow/fan-in behavior from form-field
lifecycle, prompt copy, runtime prompt prose, structured-field-path behavior,
and unrelated local files.

## Dirty File Disposition

| File | Disposition | Evidence | Recommended action |
|---|---|---|---|
| `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | Candidate, split required | Calls `auto_bind_targeted_underlag_for_text_composer` after skeleton materialization, removes `_attach_unreferenced_form_fields_to_final_step`, and changes `input_fields` / `uses_input_fields` schema prose. | Include only in the Worker slice if the slice owns create-mode compile behavior. Review hint filtering separately from dataflow auto-bind. |
| `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py` | Candidate for form-field lifecycle | Replaces a local form-field template scan with `find_unused_form_fields`. | Pair with `ai_builder_form_field_usage.py` and lifecycle tests, not with dataflow fan-in unless Judge accepts one larger combined slice. |
| `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py` | Candidate, needs cleanup before commit | New canonical predicate for unused form fields, but exposes `iter_step_templates` and has explanatory docstrings that should be tightened before production. | Include in a form-field lifecycle slice after trimming public surface to what callers need. |
| `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py` | Candidate for create-mode repair wording | Removes contradictory guidance that told outline-mode planner not to author low-level `input_source`. | Include only with create-mode schema/feedback copy tests. |
| `backend/src/intric/flows/ai_builder/ai_builder_prompts.py` | Candidate, high slop risk | Updates Swedish hints from `form_fields` to create-mode `input_fields` / `uses_input_fields`, but duplicates create/edit branches. | Defer or refactor only in a prompt-copy slice. Do not include in the first dataflow Worker unless needed for tests. |
| `backend/src/intric/flows/ai_builder/ai_builder_structured_field_paths.py` | Candidate micro-slice, unsafe without focused tests | Accepts root array paths by changing the terminal `expecting_index` return to `None`. | Separate micro-slice. Must prove nested invalid paths still fail and runtime resolver accepts whole-array refs. |
| `backend/src/intric/flows/runtime/step_execution_runtime.py` | Outside current create/dataflow slice | Adds runtime assistant prose for document outputs. | Defer. It is runtime prompt quality, not backend-owned create dataflow mechanics. |
| AI Builder create/dataflow tests | Candidate | New tests cover audio artifact fan-in, previous-step JSON-prior under-bind, source-underlag preservation, text-prior soft cap, and simple-flow no-op behavior. | Use selectively with the production files they validate. Avoid committing test-only expectations for deferred source. |
| `test_ai_builder_form_field_lifecycle.py` and `test_ai_builder_golden_coverage_matrix.py` | Candidate for form-field lifecycle | Reframes declare-only fields as unreferenced instead of silently attached. | Pair with form-field predicate and outline compile changes if Judge chooses that slice. |
| `test_ai_builder_prompts.py` and `test_ai_builder_create_feedback.py` | Candidate for copy/schema semantics | Pins changed prompt and feedback wording. | Include only with the matching prompt/feedback source changes. |
| `.devcontainer/*` | Unrelated | Devcontainer edits are outside the goal. | Do not touch, stage, commit, or format. |
| `scripts/run_codex_review.sh`, `PRODUCT.md`, `utvecklingssamtal.mp3` | Do-not-touch | User-local baseline / explicit do-not-touch. | Do not touch, stage, commit, or format. |
| Deleted `docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md` and broad `docs/refactor/*` / `flow_ai_builder_*.md` files | Unrelated to next Worker | Broad planning/doc changes are not required to prove a deterministic dataflow fix. | Do not stage for the implementation slice. |

## Candidate Phase Groups

### Group A: Create Dataflow Fan-In / Source-Underlag Slice

Purpose: prove the known bad meeting-flow class cannot silently drop earlier
structured JSON sections or transcript/source material.

Candidate files:

- `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`
- `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py` if a
  small cleanup is needed, though it is currently clean in git status.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
- Goal receipt files under `docs/goals/flow-ai-builder-quality-hardening/`

Evidence:

- The current `auto_bind_targeted_underlag_for_text_composer` owner already
  captures the backend-owned mechanic: rewrite the last compositional text step
  to `previous_step` plus explicit `uses_previous_fields` across JSON priors
  while preserving text priors via `uses_previous_outputs`
  (`backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py:237`).
- The dirty compiler tests include audio DOCX/PDF shapes where the body step
  must reference multiple JSON priors and the transcript source
  (`backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:2905`,
  `:2997`, `:3350`, `:3549`, `:3682`).
- The dirty critic tests cover the opposite under-bind shape: final text
  composer reads `previous_step` with multiple JSON priors but no explicit
  structured selectors
  (`backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py:2346`).

Required fixes before commit:

- Remove or reduce long test/source comments that narrate implementation rather
  than behavior.
- Replace `# type: ignore[arg-type]` in tests with typed parametrization or a
  local cast if unavoidable.
- Confirm the slice still includes a real red/recovery story. Because tests and
  source were already dirty together, Judge may accept "existing dirty recovery
  with prior green validation" instead of a new red observation, but this must
  be explicit.
- Keep `ai_builder_prompts.py`, `ai_builder_create_feedback.py`, and
  form-field lifecycle changes out unless the selected tests require them.

Validation:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py \
  -q
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_create_outline.py \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
cd backend && uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_create_outline.py \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
cd backend && uv run ruff format --check \
  src/intric/flows/ai_builder/ai_builder_create_outline.py \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
git diff --check -- \
  backend/src/intric/flows/ai_builder/ai_builder_create_outline.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py
```

### Group B: Create/Form-Field Lifecycle Slice

Purpose: stop silently attaching unreferenced create-mode input fields to the
final step and instead surface unused field declarations through one shared
predicate.

Candidate files:

- `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`
- `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py`
- `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py`

Risks:

- The new predicate file earns its place only if both post-compile lint and the
  critic use it. If only one caller remains, inline it.
- `iter_step_templates` should probably stay private unless a second external
  caller needs it.
- The outline compile context filtering should be moved closer to form-field
  compilation if Judge sees it as misplaced in `compile_outline_to_create_draft`.

Validation:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py \
  tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py \
  -q
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_create_outline.py \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  src/intric/flows/ai_builder/ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py \
  tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py
```

### Group C: Structured Field Path Array Root Micro-Slice

Purpose: allow whole-array structured refs such as `risker` while still
rejecting invalid traversal like `risker.rubrik`.

Candidate files:

- `backend/src/intric/flows/ai_builder/ai_builder_structured_field_paths.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py`

Risks:

- Current source change broadens the final return to `None` whenever traversal
  ends while `expecting_index` is true. That seems intended for the root array
  itself but must not mask malformed nested paths.
- Needs runtime-template compatibility evidence before being included in a
  dataflow/fan-in commit, because `uses_previous_fields` ultimately renders to
  template refs.

### Group D: Prompt / Feedback Copy Slice

Purpose: align Swedish planner hints and repair feedback with create-mode
schema mechanics.

Candidate files:

- `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py`
- `backend/src/intric/flows/ai_builder/ai_builder_prompts.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompts.py`

Risks:

- This is behavior-adjacent prompt copy and should not be mixed into dataflow
  mechanics unless it unblocks a failing test.
- The create/edit hint branches in `ai_builder_prompts.py` duplicate long
  Swedish strings; refactor or defer to keep reviewability high.

## Recommendation For T006 Judge

Choose Group A if the goal is to move directly toward the user's known bad
meeting audio-to-DOCX failure. It has the highest product value and the closest
test evidence for:

- final composer/renderer cannot consume only the last JSON section;
- section extractors/composers preserve targeted source text;
- easy two-step flows remain unchanged;
- compare/aggregate fan-in stays allowed.

However, Group A should be narrowed before Worker starts. The allowed files
should be limited to create/dataflow source and its direct tests, with explicit
stop conditions for prompt copy, form-field lifecycle, structured-path loosening,
runtime prose, and broad docs.

If Judge requires a strict red observation and cannot accept the already-dirty
recovery evidence, choose Group C or a new still-red sub-slice instead. Do not
stage the full dirty draft.

## Current Verification Evidence

Previously run focused baseline:

```text
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py -q
```

Result: `196 passed`.

```text
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/ai_builder_prompts.py src/intric/flows/ai_builder/ai_builder_structured_field_paths.py src/intric/flows/ai_builder/ai_builder_validation_quality.py src/intric/flows/ai_builder/ai_builder_form_field_usage.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py
```

Result: `0 errors`.

Docker note: the tool policy blocked direct Docker inspection despite user
permission to use `docker exec eneo-41ae93-eneo-1`. Prefer the host-local `uv`
fallback unless Docker execution becomes callable.
