# T001 Scout Baseline Receipt

## Dirty State

Current branch: `feature/refactor-flows-flowai`, ahead of origin by 6 commits.

| Path | Disposition | Evidence / Reason |
|---|---|---|
| `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | task-relevant candidate | Removes silent final-step form-field attachment, filters runtime hints to referenced fields, and calls `auto_bind_targeted_underlag_for_text_composer` after skeleton materialization. |
| `backend/src/intric/flows/ai_builder/ai_builder_prompts.py` | task-relevant candidate | Updates Swedish create/edit hints to teach `input_fields` plus `uses_input_fields` instead of bare `form_fields`; improves MCP wording. |
| `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py` | task-relevant candidate | Reuses the new shared form-field usage predicate for unused-field linting. |
| `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py` | task-relevant candidate | New narrow owner for determining whether declared form fields are referenced by step templates. |
| `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py` | task-relevant candidate | Stops giving contradictory repair guidance about `input_source` in create mode, where the outline schema intentionally strips low-level source mechanics. |
| `backend/src/intric/flows/ai_builder/ai_builder_structured_field_paths.py` | task-relevant candidate, needs review | Allows array field path roots such as `risker`; review the final `return None` shape before commit because it may be broader than intended if nested invalid paths are not still covered by tests. |
| `backend/src/intric/flows/runtime/step_execution_runtime.py` | potentially relevant but outside first dataflow slice | Adds artifact-output prose guidance. Keep out of the first commit unless Judge explicitly includes runtime prompt quality. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` | task-relevant candidate | Adds regression coverage for JSON-prior scaling and form-field lifecycle behavior. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py` | task-relevant candidate | Adds fan-in and targeted-underlag critic coverage for many JSON priors vs many text priors. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | task-relevant candidate | Reframes declare-only form fields as invalid/unreferenced instead of silently attached. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py` | task-relevant candidate | Covers removal of contradictory `input_source` repair guidance. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py` | task-relevant candidate | Updates coverage row naming and edit parity exception for create-only declare-field behavior. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompts.py` | task-relevant candidate | Pins create-mode hint language. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py` | task-relevant candidate | Pins root array field path acceptance. |
| `.devcontainer/devcontainer.json`, `.devcontainer/docker-compose.yml` | unrelated do-not-stage | Devcontainer changes are outside AI Builder quality slice. |
| `scripts/run_codex_review.sh`, `PRODUCT.md`, `utvecklingssamtal.mp3` | unrelated do-not-touch | Explicit user baseline. |
| `docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md` deletion and new `docs/refactor/*`, `flow_ai_builder_*.md`, `docs/gemini_*.md` | unclassified docs, do-not-stage for first Worker | Broad docs are not needed for the first deterministic source/test slice unless Judge explicitly includes them. |
| `docs/goals/flow-ai-builder-quality-hardening/*` | goal-board process files | Required by the current `/goal` operating loop; may be staged only with a coherent phase receipt if the commit policy allows process docs. |

## Canonical Owners

| Concept | Canonical owner found | Notes |
|---|---|---|
| Create-mode semantic outline to backend mechanics | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | `compile_outline_to_create_draft` owns translating semantic outline fields into `FlowCreateDraft` mechanics. |
| Step materialization and terminal artifact slots | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py` | Skeleton plan owns structural shape such as terminal artifact step insertion. |
| Source-material / underlag boundary detection | `backend/src/intric/flows/ai_builder/ai_builder_source_material.py` | Existing narrow owner for whether a step that consumes JSON also receives source text. |
| Targeted structured fan-in mechanics | `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py` | Existing `auto_bind_targeted_underlag_for_text_composer` is the current backend-owned binding normalizer for create drafts. |
| Create/edit quality critic invariants | `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py` | Already owns semantic critic rules for terminal output alignment, source-material underlag, and structured fan-in. |
| Post-compile quality warnings | `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py` | Should reuse shared predicates instead of duplicating template scans. |
| Form-field usage predicate | `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py` | New narrow file earns its place if both critic and validation use the same predicate. |
| Edit form-field tool schema | `backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py` | Gap remains: `FlowEditDraft.form_operations` exists, but the tool schema still does not expose `form_operations`. |

## Existing Tests / Factories To Extend

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` already has helper `_field` and many create compiler shape tests.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py` already has `_step`, `_context_with_signals`, `evaluate_critic_invariants`, and invariant-specific test classes.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` owns create-mode form-field lifecycle expectations.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py` owns create repair feedback messages.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py` owns path validity tests.

## Verification Commands Found / Run

Docker note: `docker ps --format '{{.Names}}'` was blocked by the local tool policy before Docker execution despite user permission. Use host-local commands as fallback unless Docker becomes callable later.

Focused commands run locally:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py \
  -q
```

Result: `196 passed in 0.96s`.

```bash
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_create_outline.py \
  src/intric/flows/ai_builder/ai_builder_prompts.py \
  src/intric/flows/ai_builder/ai_builder_structured_field_paths.py \
  src/intric/flows/ai_builder/ai_builder_validation_quality.py \
  src/intric/flows/ai_builder/ai_builder_form_field_usage.py \
  tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py \
  tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py \
  tests/unittests/flows/ai_builder/test_ai_builder_structured_field_paths.py
```

Result: `0 errors, 0 warnings, 0 informations`.

Likely final gates for the first source/test slice:

```bash
cd backend && uv run ruff check <touched source/test files>
cd backend && uv run ruff format --check <touched source/test files>
cd backend && uv run lint-imports --no-cache
git diff --check -- <touched source/test files and goal docs>
```

## Scout Recommendation

The first safe Worker slice should not start from scratch. The worktree already contains a coherent task-relevant implementation/test draft for:

1. not silently attaching unused create-mode form fields to the final step,
2. backend-owned targeted fan-in for many JSON priors while still avoiding giant text-body fan-in,
3. critic coverage for previous-step composers that drop earlier structured JSON priors,
4. prompt/feedback wording aligned with create-mode semantics.

Judge should either:

- accept this as the first Worker slice to harden, verify, self-review, and commit, after adding any missing red-test coverage if a still-unfixed defect can be found; or
- narrow to the missing edit-mode `form_operations` schema exposure if the pre-existing dirty source makes a true red-test phase for the create dataflow slice impossible.

Important blocker risk: because task-relevant production and tests are already dirty together, observing a fresh red test for the exact existing draft may be impossible without destructive checkout. The Judge must decide whether to proceed by validating the existing draft as user/other-agent work or select a still-red sub-gap such as edit `form_operations`.
