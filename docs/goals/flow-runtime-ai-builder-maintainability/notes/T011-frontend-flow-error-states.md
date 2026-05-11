# T011 Frontend Flow Error States Scout

## TL;DR

- The backend public API error contracts for the golden journey are stable enough
  to audit frontend rendering.
- Flow run creation already routes server errors through one Flow-specific mapper,
  but the mapper does not know the new public error codes.
- Review checkpoint actions render stale revisions explicitly, but typed contract
  violations and most review lifecycle codes fall through to backend-readable text.
- Artifact/evidence/load/cancel/redispatch paths mostly use generic messages; do
  not broaden into those until the backend codes are part of the public golden path.
- Recommended next step: Judge one narrow frontend Worker that makes public
  Flow runtime/review error codes actionable and localized without redesigning UI.

## Scope

Read-only scout for frontend-visible Flow error states after the public API
golden journey exposed runtime and review checkpoint paths.

Focused paths:

- Flow run creation and run-contract load.
- Missing required runtime step inputs.
- Review checkpoint edit conflicts and contract validation.
- Review approve/reject/resume lifecycle errors.
- Artifact/output/evidence fetching, cancel, redispatch, and retry/resume errors.

## Current Frontend Owners

| Surface | Current owner | Evidence | Current behavior |
|---|---|---|---|
| Flow run contract load | `FlowRunDialog.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:306` | Uses `getFlowRuntimeErrorMessage(...)` for `runContractError`. |
| Flow run create | `FlowRunDialog.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:1040` | Builds payload, step inputs, idempotency key, and calls `intric.flows.runs.create(...)`; caught errors go through `getFlowRuntimeErrorMessage(...)`. |
| Runtime file upload | `FlowRunDialog.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:581` | Per-file upload failures go through `getFlowRuntimeErrorMessage(...)`. |
| Flow runtime error mapping | `flowRuntimeErrorMapping.ts` | `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.ts:3` | Maps template and rerun codes only, using hardcoded Swedish strings. |
| Run list/load errors | `FlowRunsTable.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:180` | List load failures go through `getFlowRuntimeErrorMessage(...)`; cancel/redispatch/artifact errors use generic toasts. |
| Review checkpoint actions | `FlowRunReviewCheckpointPanel.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte:54` | Load/edit/approve/reject/resume errors use local `getReviewActionErrorMessage(...)`; only stale revision has explicit mapping. |
| Review checkpoint tests | `FlowRunReviewCheckpointPanel.test.ts` | `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts:139` | Tests stale revision but not typed contract violations or other review lifecycle codes. |
| Evidence/artifact output | `FlowRunEvidence.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:76` | Evidence load flips a boolean; artifact/evidence export download failures use generic messages. |

## Backend Error Contracts Requiring Frontend Attention

| Backend code | Backend evidence | Frontend explicit today? | Current fallback | Recommendation |
|---|---|---:|---|---|
| `flow_run_required_step_input_missing` | `backend/tests/integration/flows/test_flow_consumer_api_contract.py:489` asserts omitted `step_inputs` returns the code, message, and `context.step_ids`. Router docs list the code at `backend/src/intric/flows/api/flow_run_execution_router.py:207`. | No | Run create uses `getFlowRuntimeErrorMessage(...)`, but `flowRuntimeErrorMapping.ts:3` has no entry. The user likely sees backend text only. | Add an explicit localized/actionable mapping. This is part of the public API golden journey. |
| `flow_run_top_level_file_ids_not_supported` | `backend/tests/integration/flows/test_flow_consumer_api_contract.py:434` asserts code, message, and context pointing to `step_inputs[step_id].file_ids`. | No | Same run-create mapper fallback. | Add explicit mapping. This is a common API-consumer migration error and should point clients to step inputs. |
| `flow_run_idempotency_conflict` | `backend/tests/integration/flows/test_flow_consumer_api_contract.py:352` asserts conflict code. Router docs define behavior at `backend/src/intric/flows/api/flow_run_execution_router.py:54`. | No | Same run-create mapper fallback. | Add explicit mapping for retry UX; clients should not blindly retry with changed input and same key. |
| `typed_io_contract_violation` | Review edit docs list code and context at `backend/src/intric/flows/api/flow_run_execution_router.py:467`; HTTP tests assert the code and context at `backend/tests/integration/flows/test_flow_consumer_api_contract.py:555`. | No | Review panel returns `error.getReadableMessage()` at `FlowRunReviewCheckpointPanel.svelte:87`. | Add review/action mapping that tells user the edited JSON does not match the step output contract and should be corrected before saving. |
| `flow_review_stale_revision` | Review docs list stale behavior at `backend/src/intric/flows/api/flow_run_execution_router.py:146`; frontend test covers it at `FlowRunReviewCheckpointPanel.test.ts:139`. | Yes | N/A | Keep. Consider moving into the shared Flow error-code mapping so run/review code uses one owner. |
| `flow_review_not_active` | Router docs list for edit/approve/reject at `backend/src/intric/flows/api/flow_run_execution_router.py:469` and `backend/src/intric/flows/api/flow_run_execution_router.py:535`. | No | Backend-readable message in review panel. | Add explicit mapping if a Worker touches review lifecycle errors. |
| `flow_review_checkpoint_not_found` | Router 404 examples use the code at `backend/src/intric/flows/api/flow_run_execution_router.py:492`. | No | Backend-readable message in review panel. | Add explicit mapping for stale/opened tabs or deleted runs; should invite reload. |
| `flow_review_reject_reason_required` / `flow_review_reject_reason_too_long` | Router reject docs list these at `backend/src/intric/flows/api/flow_run_execution_router.py:590`. | Partly local | UI disables reject when blank at `FlowRunReviewCheckpointPanel.svelte:172`; no server-code mapping. | Defer unless the Worker touches reject lifecycle codes. |
| `flow_review_idempotency_key_required` / `flow_review_not_approved` / `flow_review_already_resumed` / `flow_review_rejected` / `flow_review_cancelled` | Router resume docs list these at `backend/src/intric/flows/api/flow_run_execution_router.py:650`. | No | Backend-readable message in review panel. | Add explicit mapping if resume UX is in Worker scope. At minimum map `already_resumed`, `not_approved`, `rejected`, and `cancelled` to reload/actionable text. |

## Evidence Details

### Run Creation

`FlowRunDialog.svelte:1040` builds the final run payload from the run contract,
including `step_inputs`, then posts via `intric.flows.runs.create(...)`.
The catch block at `FlowRunDialog.svelte:1080` displays
`getFlowRuntimeErrorMessage(...)`, so the frontend already has one entry point
for server-side run-create errors.

The problem is the mapper. `flowRuntimeErrorMapping.ts:3` maps template errors
and `flow_run_rerun_step_inputs_unsupported`, but none of the public run-create
codes from the new API contract. Its messages are also hardcoded Swedish strings
instead of using the app's message catalogs.

### Review Checkpoints

`FlowRunReviewCheckpointPanel.svelte:82` handles only
`flow_review_stale_revision` explicitly. For `typed_io_contract_violation`, the
panel falls back to `IntricError.getReadableMessage()`, even though the backend
documents and tests a stable code plus context for contract violations.

The existing review panel test at
`FlowRunReviewCheckpointPanel.test.ts:139` proves stale revision rendering, but
there is no equivalent test for `typed_io_contract_violation`,
`flow_review_not_active`, `flow_review_checkpoint_not_found`, or resume lifecycle
codes.

### Artifact And Evidence Fetching

`FlowRunEvidence.svelte:76` loads run evidence and only records a boolean
`loadError`. Artifact and evidence export download failures at
`FlowRunEvidence.svelte:133` and `FlowRunEvidence.svelte:199` use generic
messages. `FlowRunsTable.svelte:281`, `FlowRunsTable.svelte:296`, and
`FlowRunsTable.svelte:319` also use generic artifact, redispatch, and cancel
toasts.

These are not the first frontend Worker target unless Scout/Judge confirms the
backend publishes stable machine-readable codes for those specific paths. The
highest-ROI first frontend target is run-create plus review-checkpoint codes
already covered by the public API golden journey.

## Maintainability Findings

| Finding | Why it matters | Evidence | Proposed owner | Confidence |
|---|---|---|---|---|
| Flow runtime error messages have one mapper but not one language owner. | Hardcoded Swedish in a TS utility bypasses the i18n catalogs and makes future English/API-consumer UX drift likely. | `flowRuntimeErrorMapping.ts:3`, `frontend/apps/web/messages/en.json:1902`, `frontend/apps/web/messages/sv.json:1902`. | Keep Flow-domain code extraction in `flowRuntimeErrorMapping.ts`; route message text through app message catalogs from the Svelte caller or a narrow message resolver. | Medium |
| Review checkpoint error mapping is local and partly duplicated with runtime mapping. | Future review endpoint codes can be fixed in one component while run-create and run-list behavior stay generic. | `FlowRunReviewCheckpointPanel.svelte:82`; `flowRuntimeErrorMapping.ts:75`. | Prefer one Flow-domain code-to-message owner for stable Flow API codes, then call it from run and review surfaces. | High |
| The server contract has enough context for better UI but the frontend currently ignores it. | API consumers and users lose actionable guidance when `context.step_ids` or contract-violation fields are available but not surfaced. | `test_flow_consumer_api_contract.py:489`, `test_flow_consumer_api_contract.py:555`. | First pass can map stable codes to action text; a later pass can highlight exact controls by `step_ids` if needed. | High |
| Evidence/artifact failures are generic. | Users may not know whether output is missing, unavailable, forbidden, or still generating. | `FlowRunEvidence.svelte:133`, `FlowRunEvidence.svelte:199`, `FlowRunsTable.svelte:281`. | Defer until backend codes for those paths are confirmed and tested. | Medium |

## Bounded Worker Candidate

Objective:

Make the frontend Flow run/review error handling consume the stable backend
Flow API error codes introduced or exercised by the public API golden journey,
without redesigning Flow UI.

Allowed files:

- `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.ts`
- `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.test.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts`
- `frontend/apps/web/messages/en.json`
- `frontend/apps/web/messages/sv.json`
- `docs/goals/flow-runtime-ai-builder-maintainability/notes/T022-frontend-flow-error-contracts.md`
- `docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

Candidate scope:

- Add explicit, localized messages for:
  - `flow_run_required_step_input_missing`
  - `flow_run_top_level_file_ids_not_supported`
  - `flow_run_idempotency_conflict`
  - `typed_io_contract_violation`
  - `flow_review_stale_revision`
  - `flow_review_not_active`
  - `flow_review_checkpoint_not_found`
  - `flow_review_not_approved`
  - `flow_review_already_resumed`
  - `flow_review_rejected`
  - `flow_review_cancelled`
- Keep UI rendering narrow: existing toasts and alerts should show better text;
  do not redesign the run dialog, review panel, evidence panel, or history table.
- Prefer moving review-code extraction/message mapping to a Flow-domain utility
  over growing another local component switch.
- Avoid broad i18n refactor. If the clean solution requires a new generated
  message access pattern in non-Svelte TS, return to Judge before implementing.

Red tests:

- `flowRuntimeErrorMapping.test.ts` should fail before the Worker because the
  new run-create codes return `null`/fallback.
- `FlowRunReviewCheckpointPanel.test.ts` should fail before the Worker because
  `typed_io_contract_violation` renders backend-readable text instead of the
  localized/actionable review contract message.

Verification:

- `cd frontend/apps/web && bunx vitest run src/lib/features/flows/flowRuntimeErrorMapping.test.ts src/lib/features/flows/components/FlowRunReviewCheckpointPanel.test.ts`
- `cd frontend/apps/web && bun run i18n:compile`
- `cd frontend/apps/web && bun run check`
- `cd frontend/apps/web && bun run lint`
- `git diff --check`
- `node /Users/ccimen/.codex/skills/goal-maker/scripts/check-goal-state.mjs docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

Stop if:

- A clean solution requires redesigning Flow UI or changing backend contracts.
- The i18n/message access pattern in TS cannot be done without a broad generated
  client or Paraglide refactor.
- The Worker needs files outside the allowed list.
- The change introduces `any`, `as any`, `@ts-ignore`, or another parallel error
  mapping owner.
- Artifact/evidence/cancel/redispatch codes start expanding the slice without
  stable backend code evidence.

## Do-Nothing Verdict

Do not do nothing. The frontend has a real owner path for Flow runtime errors,
but public API golden-journey codes currently fall through to generic or backend
messages. A narrow frontend follow-through slice is justified after Judge/Claude
confirm the message ownership shape.
