# T021 Frontend Error Contract Judge

## Decision

Activate one narrow frontend Worker for Flow API error-contract rendering after
Claude green-lights this revised plan.

The Worker should consolidate Flow run/review machine-readable error-code
handling in `flowRuntimeErrorMapping.ts`, migrate Flow-domain messages to the
app message catalogs, and remove the review panel's local error-code switch.

## Claude Iteration 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted blockers:

- Commit to a single i18n/resolver shape before implementation.
- Keep tests locale-independent or explicitly pin locale.
- Reconcile the allowed-files list with current call sites.
- Delete the local `getReviewActionErrorMessage` switch from
  `FlowRunReviewCheckpointPanel.svelte`, not merely add another mapper.
- Preserve backend error context in the resolver signature now, even if the
  first UI pass only renders actionable text.
- Avoid a half-migration where old codes remain hardcoded Swedish while new
  codes use i18n.

Codex verification:

- `import { m } from "./src/lib/paraglide/messages.js"` works from a plain TS/JS
  module and can resolve both English and Swedish messages by locale.
- Current call sites are:
  - `FlowRunDialog.svelte`
  - `FlowRunsTable.svelte`
  - `FlowTemplateState.svelte.ts`
  - `templateFillErrors.ts`
  - `FlowRunReviewCheckpointPanel.svelte`
- Because existing public helper signatures can remain stable as wrappers, only
  the review panel call site needs to change in this Worker.

## Selected Shape

Do not make `flowRuntimeErrorMapping.ts` only a string lookup table. Make it the
single Flow API error parser and descriptor owner, while preserving current
string-returning exports as compatibility wrappers for existing frontend
callers.

Code shape:

```ts
export type FlowApiErrorCode =
  | "flow_run_required_step_input_missing"
  | "flow_run_top_level_file_ids_not_supported"
  | "flow_run_idempotency_conflict"
  | "typed_io_contract_violation"
  | "flow_review_stale_revision"
  | "flow_review_not_active"
  | "flow_review_step_result_not_found"
  | "flow_review_checkpoint_not_found"
  | "flow_review_reject_reason_required"
  | "flow_review_reject_reason_too_long"
  | "flow_review_idempotency_key_required"
  | "flow_review_not_approved"
  | "flow_review_already_resumed"
  | "flow_review_rejected"
  | "flow_review_cancelled"
  | "flow_template_invalid_archive"
  | "flow_template_corrupted_archive"
  | "flow_template_macro_not_allowed"
  | "flow_template_missing_required_parts"
  | "flow_template_not_accessible"
  | "flow_template_read_only"
  | "flow_template_unsupported_extension"
  | "flow_template_missing_content"
  | "flow_run_rerun_step_inputs_unsupported";

export type FlowApiErrorContext = {
  step_ids?: string[];
  checkpoint_id?: string;
  step_id?: string;
  step_order?: number;
  payload_field?: string;
};

export type FlowApiErrorDescriptor = {
  code: FlowApiErrorCode;
  messageKey: FlowApiErrorMessageKey;
  context: FlowApiErrorContext;
};

export function extractFlowApiError(error: unknown): {
  code: FlowApiErrorCode;
  context: FlowApiErrorContext;
} | null;

export function describeFlowApiError(error: unknown): FlowApiErrorDescriptor | null;

export function getFlowRuntimeErrorMessage(error: unknown, fallbackMessage: string): string;

export function getFlowRuntimeErrorMessageByCode(code: string | null | undefined): string | null;
```

Implementation notes:

- `describeFlowApiError(...)` and `extractFlowApiError(...)` are the primary
  test targets. Tests assert descriptors and message keys, not raw translated
  strings.
- `getFlowRuntimeErrorMessage(...)` and `getFlowRuntimeErrorMessageByCode(...)`
  remain stable wrappers for current call sites and resolve descriptors through
  `m.*`.
- Use explicit `flow_error_<backend_code>` catalog keys for backend Flow API
  codes. Use the same prefix for existing template/rerun codes migrated from
  hardcoded Swedish strings.
- Keep `FlowApiErrorMessageKey` as a closed union. If several codes share the
  same user-facing copy, share the message key intentionally in the descriptor
  switch rather than inventing a second text.
- Use an explicit `switch`/record typed by `FlowApiErrorCode` and
  `FlowApiErrorMessageKey`; do not use broad `Record<string, string>` for the
  public code contract.
- Move existing hardcoded Swedish template/rerun strings to `en.json` and
  `sv.json` in the same slice. Do not leave the file half-migrated.
- Split missing-template-content substring classification into a small named
  function. Keep it in the string-returning wrapper fallback path, not in the
  typed backend-code descriptor path, because it is not a real backend code.
- Preserve backend context in `extractFlowApiError(...)` so later UI highlight
  work can use `context.step_ids` or review fields without changing the parser.
- Treat missing or malformed context as `{}` and still return the descriptor for
  a known code. The immediate UX should remain actionable even if context is
  absent; backend/contract drift is covered by API tests and descriptor coverage.
- One short comment is allowed beside the message resolver cast if needed: the
  cast is bounded by a closed `FlowApiErrorMessageKey` union and the coverage
  test. Do not add tutorial comments or task references in source.

## Selected Worker

Objective:

TDD-consolidate Flow API error-code rendering so stable backend Flow run/review
codes resolve to localized, actionable frontend messages through one
Flow-domain parser/descriptor owner, while preserving existing string-returning
helper call sites and removing the review panel's local code switch.

Allowed files:

- `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.ts`
- `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.test.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts`
- `frontend/apps/web/messages/en.json`
- `frontend/apps/web/messages/sv.json`
- `docs/goals/flow-runtime-ai-builder-maintainability/notes/T022-frontend-flow-error-contracts.md`
- `docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

Allowed backend-code scope:

- Run-create/API-consumer codes:
  - `flow_run_required_step_input_missing`
  - `flow_run_top_level_file_ids_not_supported`
  - `flow_run_idempotency_conflict`
- Review checkpoint codes documented in the public review endpoints:
  - `typed_io_contract_violation`
  - `flow_review_stale_revision`
  - `flow_review_not_active`
  - `flow_review_step_result_not_found`
  - `flow_review_checkpoint_not_found`
  - `flow_review_reject_reason_required`
  - `flow_review_reject_reason_too_long`
  - `flow_review_idempotency_key_required`
  - `flow_review_not_approved`
  - `flow_review_already_resumed`
  - `flow_review_rejected`
  - `flow_review_cancelled`
- Existing Flow template/rerun codes already handled by the mapper:
  - `flow_template_*`
  - `flow_run_rerun_step_inputs_unsupported`

Explicitly deferred:

- `flow_run_concurrency_limit_reached`, `flow_input_required_field_missing`,
  `flow_input_invalid_number`, and `flow_run_input_payload_too_large`: these are
  public create-run codes, but they are not part of the newly exercised golden
  journey path and may need closer alignment with form-field validation UX.
- Rerun-specific codes beyond the existing
  `flow_run_rerun_step_inputs_unsupported`: they belong to a later rerun UX
  slice.
- Artifact/evidence/cancel/redispatch failure codes: current frontend messages
  remain generic until backend publishes stable codes and tests for those paths.

## Red Tests

The Worker must prove red before implementation:

- `flowRuntimeErrorMapping.test.ts`:
  - `describeFlowApiError(...)` returns a descriptor for
    `flow_run_required_step_input_missing` and preserves `context.step_ids`.
  - `describeFlowApiError(...)` returns a descriptor for
    `typed_io_contract_violation` and preserves review context fields.
  - Every code in the typed Flow API code list has a descriptor.
  - Existing template/rerun codes no longer depend on raw Swedish strings.
- `FlowRunReviewCheckpointPanel.test.ts`:
  - A `typed_io_contract_violation` edit error renders the localized/actionable
    review contract message instead of backend-readable text.
  - The existing stale-revision test remains green through the shared mapper.
  - `flow_review_step_result_not_found` receives a descriptor even if no panel
    behavior test directly exercises that rare edit-path branch.

## Verification

- `cd frontend/apps/web && bunx vitest run src/lib/features/flows/flowRuntimeErrorMapping.test.ts src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts`
- `cd frontend/apps/web && bunx vitest run src/lib/features/flows`
- `cd frontend/apps/web && bun run i18n:compile`
- `cd frontend/apps/web && bun run check`
- `cd frontend/apps/web && bun run lint`
- `git diff --check`
- `node /Users/ccimen/.codex/skills/goal-maker/scripts/check-goal-state.mjs docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

## Stop Conditions

- A clean implementation requires changing backend contracts or generated API
  client types.
- The resolver cannot import and use Paraglide messages from plain TS without
  broad build/config changes.
- The existing string-returning helper signatures cannot remain stable without
  changing more frontend call sites.
- The implementation needs files outside the allowed list.
- The slice expands into UI redesign, artifact/evidence/cancel/redispatch
  behavior, or broad frontend error-boundary refactoring.
- It introduces `any`, `as any`, `@ts-ignore`, or a second Flow error-code owner.
- It keeps both hardcoded Swedish messages and i18n catalog messages in the same
  mapper.
- Tests assert raw translated strings instead of descriptors/message keys,
  except where asserting the review panel renders the localized user-visible
  message.
- `rg "getReviewActionErrorMessage" frontend/apps/web/src` returns a remaining
  source reference after implementation.

## Maintainability Impact

This slice should make `flowRuntimeErrorMapping.ts` a deeper module with a small
stable interface: parse stable Flow API errors, describe their message intent,
and preserve existing string-returning wrappers for current call sites. It
reduces fear of change because future backend Flow error-code additions have one
typed frontend owner and one coverage test instead of scattered component
switches.

## Claude Iteration 2

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Accepted non-blocking clarifications:

- Use a consistent catalog naming convention: `flow_error_<backend_code>`.
- Define `FlowApiErrorMessageKey` as a closed union and keep the wrapper cast
  narrow.
- Add a negative descriptor test for unknown errors returning `null`.
- Keep missing-template-content substring classification outside the typed
  backend-code path.
- Confirm `rg "getReviewActionErrorMessage"` after implementation so the local
  review mapper is gone.

Claude artifacts:

- `.codex/artifacts/claude-peer-loop-t021-frontend-flow-error-contract-plan-20260511T010149Z.md`
- `.codex/artifacts/claude-peer-loop-t021-frontend-flow-error-contract-plan-iteration-2-20260511T010549Z.md`
