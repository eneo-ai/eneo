# Retrospective 18 — Edit Confirmation And Published-Flow Apply UX

## TL;DR

1. The live bad DOCX output was still a dataflow/source-material ownership
   problem, not a need for more prompt words.
2. Source-material binding completeness now has one enum owner shared by
   normalization, validation, and scoring.
3. Existing-flow requirements confirmation now survives version hydration and
   old version-less draft sessions.
4. Published-flow edits now use an explicit confirm, unpublish, apply path with
   a partial-failure recovery state.
5. Local validation passed except for known unrelated `svelte-check` failures;
   Claude green-lit the slice.

## What Changed

| Area | Change |
|---|---|
| Source-material binding | Added `SourceMaterialBindingStatus` and removed duplicate boolean completeness accessors. |
| Source-material prompt construction | Preserved existing user prompt order and appended only missing structured/source references. |
| Requirements confirmation | Persisted and hydrated `requirements_version`; added a dated bridge for version-less pre-2026-05-03 draft confirmations. |
| Requirements card | Added latest real user request display and removed the collapsible height animation that produced `NaNpx` warnings. |
| Existing-flow edits | Kept latest-request display in frontend conversation state rather than backend deterministic server actions. |
| Published-flow apply | Added explicit confirm, unpublish, apply, and post-unpublish apply-failure state. |

## Checklist

| Section | Item | Result | Evidence |
|---|---|---|---|
| A | Implemented the user-requested long-term fix instead of prompt-wording only. | pass | Source-material status owner in `ai_builder_source_material.py:58-151`; normalizer and validator reuse it. |
| A | Stayed within Flow AI Builder scope. | pass | Touched files are under Flow AI Builder backend, Flow AI Builder frontend, benchmark scoring, tests, and Batch 11 docs. |
| A | Addressed Claude's accepted findings. | pass | `claude-reconciliation-18.md` records all accepted findings and resolutions. |
| B | Acceptance criteria are evidence-backed. | pass | Tests cover source-material binding status, requirements confirmation hydration, published-flow apply errors, and validator behavior. |
| C | Validation commands ran. | pass | Backend unit/integration tests, Pyright, Ruff, frontend driver tests, i18n compile, Prettier, and `git diff --check` passed. |
| C | Known validation blockers are documented. | pass | `svelte-check` still fails on unrelated generated-client, Spaces, chat, dashboard, and FlowsTable errors. |
| D | No hidden destructive published-flow mutation. | pass | `FlowAIBuilderPlanPane.svelte:137-140` requires confirmation before unpublish. |
| D | No new prompt-repair loop. | pass | `SourceMaterialBindingStatus.NEEDS_COMPLETION` controls deterministic topology completion; no retry warning was added. |
| E | Single source of truth improved. | pass | Normalizer, validator, and manual scoring share `source_material_binding_status(...)`. |
| E | Conversation-derived request display has one owner. | pass | `FlowAIBuilderChat.svelte:49-56` derives it from frontend state; backend server action code does not. |
| F | Reviewability stayed reasonable. | pass | Changes are grouped by backend source-material/confirmation owner, frontend UX, and focused tests. |
| G | Comments explain non-obvious decisions. | pass | Version-less confirmation bridge and client-side control-message filter comments document deletion/filter intent. |
| H | Tests protect behavior. | pass | `FlowAIBuilderDriver.test.ts` asserts unpublish-and-apply success/failure; backend tests assert binding status and confirmation version behavior. |
| I | Boundary discipline preserved. | pass | No ORM, router business logic, Celery, migrations, or runtime data-model changes. |
| J | Carry-forward risks recorded. | pass | Manual DOCX smoke, design-system confirm dialog, i18n wire-format debt, and Docker validation are listed below. |

Final gate: GREEN.

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1823 passed, 4 skipped`, existing warnings only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder -q` | Passed: `111 passed, 20 deselected`, existing warnings only. |
| `cd backend && uv run pyright <11.6c touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.6c touched source and test files>` | Passed. |
| `cd frontend/apps/web && bun test src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts` | Passed: `32 pass`. |
| `cd frontend/apps/web && bun run i18n:compile` | Passed. |
| `cd frontend/apps/web && bunx prettier --check <11.6c touched frontend files>` | Passed. |
| `cd frontend/apps/web && bunx svelte-check --tsconfig ./tsconfig.json` | Failed on pre-existing non-AI-Builder errors; no edited driver errors remained. |
| `git diff --check` | Passed. |

## Risks

| Risk | Mitigation |
|---|---|
| Native `window.confirm` is not the final design-system UX. | It blocks accidental unpublish now; replace with `AlertDialog` in a small frontend polish follow-up. |
| The new source-material prompt order was not live-smoke-tested with provider credentials. | Behavior tests pin deterministic binding construction; manual eval carry-forward records the live DOCX smoke. |
| Backend-rendered summary labels remain Swedish/English Python dictionaries. | Keep for this slice; move to translation-key wire format only when the API surface earns it. |
| Docker validation did not run in this tool environment. | Local validation passed; rerun in Docker where process creation is allowed. |

## Carry-Forward

| Item | Owner |
|---|---|
| Replace `window.confirm` with a design-system `AlertDialog`. | Frontend polish |
| Run live DOCX-output smoke test for the source-material ordering. | Manual eval |
| Move server-rendered requirement-summary labels to a cataloged translation contract if more locales land. | AI Builder i18n follow-up |
| Re-run Docker validation where Docker commands are not approval-blocked. | Next implementation operator |
