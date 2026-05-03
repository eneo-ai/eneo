# Claude Reconciliation 18 — Edit Confirmation And Published-Flow Apply UX

## TL;DR

1. Claude rejected the first pass until source-material binding completeness had
   one owner and published-flow edits had explicit user confirmation.
2. The accepted patch keeps source-material binding status in
   `ai_builder_source_material.py` and reuses it from normalization, validation,
   and scoring.
3. Requirements confirmation now preserves version identity and bridges only
   old pre-2026-05-03 draft sessions.
4. The requirements summary card displays the latest real user request from
   client-owned conversation state, not from backend server actions.
5. Claude green-lit the final patch with low-severity follow-ups only.

## Iterations

| Iteration | Artifact | Verdict | Green light | Minimum score | Notes |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-ai-builder-edit-confirmation-source-material-and-requirements-summary-plan-20260503T142948Z.md` | `changes_required` | `no` | n/a | Asked Codex to avoid more prompt-wording fixes and define long-term owners for source material, edit confirmation, and published-flow behavior. |
| 2 | `.codex/artifacts/claude-peer-loop-ai-builder-edit-confirmation-source-material-published-apply-ux-and-requirements-summary-verification-20260503T150947Z.md` | `changes_required` | `no` | n/a | Required explicit confirmation before unpublish, frontend-owned latest-request display, one source-material status accessor, and a bounded legacy bridge. |
| 3 | `.codex/artifacts/claude-peer-loop-ai-builder-edit-confirmation-source-material-published-apply-ux-and-requirements-summary-verification-20260503T152556Z.md` | `green` | `yes` | 8 | Verified the accepted fixes and left only follow-ups that do not block this slice. |

## Accepted Findings

| Claude finding | Codex resolution |
|---|---|
| Published-flow apply must not silently unpublish a flow. | `FlowAIBuilderPlanPane.svelte:137-140` now requires `window.confirm(...)` before calling the unpublish-and-apply path. |
| If unpublish succeeds but apply fails, the user needs a distinct recovery state. | `FlowAIBuilderDriver.ts:555-590` emits `flow_unpublished_apply_failed`; `FlowAIBuilderPlanPane.svelte:617-639` renders a dedicated banner. |
| Backend deterministic actions should not inspect mutable conversation history for latest user request display. | Removed the backend conversation-derived request path and added `latestUserRequestBefore(...)` in `FlowAIBuilderChat.svelte:49-56`. |
| Three source-material completeness predicates were harder to review than one trinary status. | `SourceMaterialBindingStatus` in `ai_builder_source_material.py:58-63` is now the canonical completeness contract. |
| Public question-mention helpers were an accidental interface. | They are private to `ai_builder_source_material.py:188-219` and are not exported. |
| The legacy version-less confirmation bridge needed a deletion trigger. | `ai_builder_requirements_state.py:101-106` documents the pre-2026-05-03 draft-session removal condition. |
| Existing source-material question order should preserve the user's prompt first. | `ai_builder_source_material.py:151-194` now appends only missing underlag after the existing prompt, and tests assert that order. |

## Disagreements And Accepted Debt

| Topic | Decision |
|---|---|
| Python-rendered Swedish/English summary labels | Accepted as debt because moving these into the frontend i18n catalog would require a server wire-format change from rendered strings to translation keys plus parameters. |
| Browser-native confirmation dialog | Accepted for this reliability slice because it provides a real destructive confirmation. A design-system `AlertDialog` is a follow-up. |
| Live DOCX smoke for prompt ordering | Not run in this tool environment because it needs the full app, provider credentials, and a published flow fixture. The risk is documented as a manual-eval carry-forward. |

## Validation Evidence

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1823 passed, 4 skipped`, existing warnings only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder -q` | Passed: `111 passed, 20 deselected`, existing warnings only. |
| `cd backend && uv run pyright <11.6c touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.6c touched source and test files>` | Passed. |
| `cd frontend/apps/web && bun test src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts` | Passed: `32 pass`. |
| `cd frontend/apps/web && bun run i18n:compile` | Passed. |
| `cd frontend/apps/web && bunx prettier --check <11.6c touched frontend files>` | Passed. |
| `cd frontend/apps/web && bunx svelte-check --tsconfig ./tsconfig.json` | Failed only on pre-existing generated-client, Spaces, chat, dashboard, and FlowsTable typing errors; the prior `FlowAIBuilderDriver.ts` errors were gone. |
| `git diff --check` | Passed. |

## Carry-Forward

| Item | Owner |
|---|---|
| Replace `window.confirm` with a design-system `AlertDialog`. | Frontend polish |
| Move server-rendered summary labels to a cataloged translation-key contract if more locales land. | AI Builder i18n follow-up |
| Run live DOCX-output smoke for the "user prompt first, data appended" source-material ordering. | Manual eval |
| Re-run Docker validation where Docker commands are not approval-blocked. | Next implementation operator |
