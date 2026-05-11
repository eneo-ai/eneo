# T022 Frontend Flow Error Contracts

## Summary

T022 consolidated Flow API error-code rendering into `flowRuntimeErrorMapping.ts` so Flow run and review errors now pass through one Flow-domain parser/descriptor owner. The review checkpoint panel no longer keeps a local backend-code switch, and the user-visible messages now live in the Paraglide message catalogs instead of hardcoded Swedish strings in the TypeScript mapper.

Claude commit-gate iteration 1 returned `changes_required`. Accepted fixes:

- Removed the dead `flow_run_review_stale_error` message key from both catalogs.
- Updated the stale-revision review-panel test to assert the new `flow_error_flow_review_stale_revision` key, avoiding a coincidence test where old and new strings matched.
- Added a test pinning that structured `response.code` wins over legacy client `error.code` for Flow API errors.
- Collapsed the duplicate message-key and resolver records into one derived `flow_error_${code}` message-key path.

## Red Test

The first test run failed before implementation:

```text
cd frontend/apps/web && bunx vitest run src/lib/features/flows/flowRuntimeErrorMapping.test.ts src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts
```

Meaningful failures:

- `describeFlowApiError is not a function`
- `FLOW_API_ERROR_CODES is not iterable`
- `m.flow_error_typed_io_contract_violation is not a function`

The component test environment was changed from `happy-dom` to `jsdom` because this workspace has `jsdom` available and the previous file-local environment could not load in this checkout.

## Changes

| File | Change |
|---|---|
| `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.ts` | Added a closed `FLOW_API_ERROR_CODES` list, descriptor type, response-context extraction, catalog-backed message resolution, and stable string wrappers for existing call sites. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte` | Removed the local `getReviewActionErrorMessage` / `getReviewErrorCode` switch and routed load/edit/approve/reject/resume errors through the shared Flow mapper. |
| `frontend/apps/web/messages/en.json` | Added English `flow_error_*` messages for current Flow run, review, template, and rerun API codes. |
| `frontend/apps/web/messages/sv.json` | Added Swedish `flow_error_*` messages for the same codes and removed the mapper as the Swedish-message owner. |
| `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.test.ts` | Added descriptor/context coverage, unknown-error fallback coverage, and a coverage test that every frontend-owned Flow API error code maps to `flow_error_<code>`. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts` | Added user-visible coverage proving a `typed_io_contract_violation` review edit error renders the localized contract message instead of the backend fallback. |

## Verification

| Command | Result |
|---|---|
| `cd frontend/apps/web && bunx vitest run src/lib/features/flows/flowRuntimeErrorMapping.test.ts src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts` | PASS, 2 files and 23 tests passed after Claude iteration 1 fixes. |
| `cd frontend/apps/web && bun run i18n:compile` | PASS. |
| `cd frontend/apps/web && bun run check` | PASS with `0 errors`; 7 existing Svelte warnings remain. |
| `cd frontend/apps/web && bunx prettier --check src/lib/features/flows/flowRuntimeErrorMapping.ts src/lib/features/flows/flowRuntimeErrorMapping.test.ts src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts messages/en.json messages/sv.json` | PASS. |
| `cd frontend/apps/web && bunx eslint src/lib/features/flows/flowRuntimeErrorMapping.ts src/lib/features/flows/flowRuntimeErrorMapping.test.ts src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts` | PASS. |
| `rg -n "flow_run_review_stale_error\|FLOW_API_ERROR_MESSAGE\|getReviewActionErrorMessage" frontend/apps/web/src frontend/apps/web/messages/en.json frontend/apps/web/messages/sv.json` | PASS, no remaining references. |
| `git diff --check` | PASS. |

Broader checks that are not clean in this checkout:

| Command | Result |
|---|---|
| `cd frontend/apps/web && bunx vitest run src/lib/features/flows` | FAIL, 5 files and 8 tests failed. Failures appear unrelated to T022, including locale-sensitive accessible-name expectations in Flow AI Builder tests, MCP persistence role-name expectations, assistant settings label expectations, and an existing Flow editor metadata-shape mismatch. The rerun after Claude iteration 1 still failed with the same failure classes and 459 passing tests. |
| `cd frontend/apps/web && bun run lint` | FAIL in `prettier --check .` before linting T022 specifically, due pre-existing formatting drift across 30 files. Touched T022 files pass targeted Prettier and ESLint. |

Broader Flow frontend failing test names from the post-fix rerun:

- `src/lib/features/flows/FlowEditor.test.ts > FlowEditor metadata commands > replaces form schema fields with persisted field shape`
- `src/lib/features/flows/ai-builder/FlowAIBuilder.test.ts > FlowAIBuilder > auto-resumes a single matching create draft instead of starting a new chat`
- `src/lib/features/flows/ai-builder/FlowAIBuilderStepCard.test.ts > FlowAIBuilderStepCard > surfaces step-scoped MCP tools before approval`
- `src/lib/features/flows/ai-builder/FlowAIBuilderStepCard.test.ts > FlowAIBuilderStepCard > emits structured step edit context instead of relying on button text`
- `src/lib/features/flows/components/FlowStepAssistantPersistence.test.ts > Flow step assistant persistence wiring > shows the active assistant's reasoning effort after switching steps`
- `src/lib/features/flows/components/FlowStepMcpPersistence.test.ts > Flow step MCP persistence wiring > saves MCP server selection as one batched payload with tool settings`
- `src/lib/features/flows/components/FlowStepMcpPersistence.test.ts > Flow step MCP persistence wiring > drops stale MCP servers that are no longer available in the space before saving`
- `src/lib/features/flows/components/FlowStepMcpPersistence.test.ts > Flow step MCP persistence wiring > saves MCP tool toggles as one batched payload`

## Maintainability Self-Review

| Rubric item | Result |
|---|---|
| Canonical ownership | Improved. `flowRuntimeErrorMapping.ts` is the single frontend Flow API error-code parser/descriptor owner. |
| Fear-of-change reduction | Improved. New backend Flow codes can be added by extending the closed code list and message-key mapping, with a test proving coverage. |
| Type safety | No new `any`, `as any`, `@ts-ignore`, or unsafe casts. The code uses `unknown` parsing and a closed `FlowApiErrorCode` union at the boundary. |
| Error contract quality | Improved for touched frontend surfaces: stable backend codes are mapped to localized, actionable frontend messages while preserving known context for future UI refinement. |
| Test quality | Behavior tests assert descriptor/context shape and visible review-panel behavior rather than private helper calls. |
| Comment quality | No source comments were added. Names and tests carry the invariant. |
| Complexity | The change avoids a second mapper and avoids broad frontend error-boundary refactoring. |
| Deletion quality | The review panel local code switch was deleted after replacement tests covered the intended behavior. |

Maintainability score: `8/10`.

## Anti-Patterns Avoided

- No new backend contract or generated-client changes.
- No second Flow error-code owner.
- No UI redesign.
- No broad artifact/evidence/cancel/redispatch handling.
- No hardcoded Swedish Flow API messages inside the mapper.
- No stale legacy review-error message key left beside the new Flow API key.
- No broad formatter run committed.
- No compatibility branch for old, unshipped review-panel error mapping.

## Residual Risk

- The mapper preserves backend context but does not yet interpolate field-specific context into messages. That is a later UX refinement once product copy is settled.
- Evidence/artifact/cancel/redispatch frontend error states still fall through generic paths and should remain deferred until backend codes for those paths are stable.
- Full Flow frontend Vitest and full frontend lint are not clean in the current checkout; targeted T022 tests, typecheck, i18n compile, ESLint, Prettier, and `git diff --check` passed.
