# Phase 7 Comment Cleanup

## TL;DR

Flow/AI Builder comment cleanup must be executable, not advisory.
Keep comments that explain intent, constraints, or non-obvious trade-offs.
Delete comments that restate control flow, describe obvious fields, preserve uncertainty, or explain compatibility paths being removed.
No commented-out code should remain in Flow/AI Builder source after the cleanup batches.
Every remaining `temporary` comment needs an owner, removal condition, and PRD/work item.

## Comment Classes

- `intent`: explains why or a non-obvious decision.
- `constraint`: explains ordering, idempotency, transaction, security, privacy, or migration constraints.
- `restate`: describes what the code already says.
- `outdated`: stale, wrong, or misleading.
- `slop`: vague AI-style explanation, apology, uncertainty, or filler.
- `todo`: TODO/FIXME/XXX.

## High-Priority File Inventory

| File | Intent/constraint comments to keep | Restating comments to delete | Outdated/slop comments to delete or rewrite | TODO verdict |
|---|---|---|---|---|
| `backend/src/intric/flows/runtime/tasks.py` | Keep `tasks.py:62-64` only if commit-heavy repository session behavior remains non-obvious. | None found in targeted scan. | Pyright global ignores at `tasks.py:43-58` should be reviewed after task loop ownership is cleaned up. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/runtime/executor.py` | Keep execution identity vs prompt key constraint in `variable_resolver.py:85-87`; in executor, keep only transaction/idempotency comments that survive terminalization command extraction. | Delete `executor.py:682-683` because `state.append_completed(step_result)` states the action. | Rewrite broad `except Exception` handling comments into failure taxonomy in terminalization work. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/flow_run_input_payload.py` | None required for simple coercion branches after names stay clear. | Delete/avoid what-comments if added while converting legacy form normalization. | `_RUN_FIELD_TYPE_LEGACY_NORMALIZATION` at `flow_run_input_payload.py:9-13` needs a deletion/backfill work item, not permanent legacy framing. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/flow_run_step_inputs.py` | Keep no comments; function names are clear. | None. | `apply_legacy_step_one_adapter` at `flow_run_step_inputs.py:104-128` should be deleted with top-level `file_ids`; do not add explanatory comments to keep it alive. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/ai_builder/ai_builder_router.py` | Keep route comments only when they explain SSE protocol or auth ordering constraints. | Delete restating docstrings at `ai_builder_router.py:181` and `:197` after policy helper replacement. | Raw request-state scope logic at `ai_builder_router.py:180-210` should move to policy; comments should not defend it as compatibility. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/ai_builder/ai_builder_materializer.py` | Keep create-mode temporary flow comment at `ai_builder_materializer.py:234` only if rewritten with owner/removal condition or invariant. | Delete section comments and field narration around create/apply phases when split by lifecycle concepts. | Rewrite `temporary` wording tied to create-mode assistant ownership into a domain invariant or work item. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | Keep comments explaining prompt/LLM contract and repair constraints, especially around parse boundary and action policy. | Delete compatibility-surface comments that only explain older tests/callers when those tests are removed. | `ai_builder_planner.py:1174-1175` compatibility comment should be removed with the compatibility surface or replaced with current contract language. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/ai_builder/question_catalog.py` | Keep slot-key mapping comment only if the bridge remains an active domain concept. | None. | `question_catalog.py:27-29` and `:62` use legacy framing; rewrite to current UI/planner key ownership or delete bridge. | No TODO/FIXME/XXX found. |
| `backend/src/intric/flows/ai_builder/deterministic_signals_extractor.py` | Keep comments explaining unsupported MIME behavior and boundary rejection if upload/runtime split remains non-obvious. | Delete explanatory prose that mirrors straightforward extraction code during split. | Legacy MIME wording at file header should become current boundary language. | No TODO/FIXME/XXX found. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts` | Keep only comments explaining Svelte lifecycle or authoring transaction constraints. | Delete instructional comments around obvious field updates and derived state. | `legacyTemplateCleanupStarted` at `FlowEditor.ts:281-285` should disappear with template cleanup rather than gain more comments. | No TODO/FIXME/XXX found. |
| `frontend/apps/web/src/lib/features/flows/components/flowRunRedispatchFeedback.ts` | None. | None. | Delete alias comment at `flowRunRedispatchFeedback.ts:7` with the alias. | No TODO/FIXME/XXX found. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte` | Keep none unless Svelte event signature genuinely remains ambiguous. | Delete comment at `FlowAIBuilderInput.svelte:74`; replace with one canonical callback signature. | Legacy string signature support should be deleted or isolated in a typed adapter. | No TODO/FIXME/XXX found. |
| `frontend/packages/intric-js/src/types/resources.d.ts` | None for generated/manual drift. | Delete manual Flow type comment at `resources.d.ts:153` after generated aliases land. | Handwritten Flow API types become generated aliases or UI-only types. | No TODO/FIXME/XXX found. |

## Comment Standard For Implementation

- Developers can read code.
- Comments explain why, not what.
- Before adding a "what" comment, improve naming, extract a function, introduce a value object, or move the code to a better module.
- A comment is suspicious if deleting it would not make the code harder to understand.
- A comment is required if deleting it would hide a non-obvious invariant, trade-off, ordering constraint, security/privacy rule, transaction rule, or debugging concern.

## Acceptance Criteria

- [ ] No commented-out code remains in Flow / AI Builder source.
- [ ] No comments merely restate function names, fields, or control flow.
- [ ] No `temporary` comments remain without owner, removal condition, and PRD/work item.
- [ ] Every kept non-trivial comment explains intent, constraint, or trade-off.
- [ ] Legacy/compatibility comments are either deleted with the old path or rewritten as current contract/invariant language.
- [ ] Comment-only cleanup is separated from behavior changes unless the source branch being deleted owns the comment.
