# T000 Codex Source Check

## Position

I agree with the new maintainability board direction: keep runtime/API P0s first, then add public API golden journeys, typed data-boundary work, and proof-backed cleanup. The key correction from the older board is valid: because Flows and Flow AI Builder are pre-production, legacy/fallback code should not be kept for hypothetical external users. It should still be deleted only after local proof, replacement behavior tests, and fixture/migration cleanup.

## Source Evidence Anchors

### Required Runtime Inputs

- `backend/src/intric/flows/application/flow_run_service.py:459` gates runtime step-input validation behind `if step_inputs is not None`.
- `backend/src/intric/flows/application/flow_run_service.py:473-481` normalizes and validates submitted step inputs only inside that branch.
- `backend/src/intric/flows/flow_run_step_inputs.py:196-207` already detects missing required runtime inputs and raises `flow_run_required_step_input_missing`.
- `backend/src/intric/flows/application/flow_run_service.py:806-836` builds the create-run idempotency fingerprint from `input_payload_json`, so any successful-request fingerprint behavior change must define and test whether omitted `step_inputs` and `{}` share the same canonical fingerprint.

Codex recommendation: keep required runtime input enforcement as the likely first Worker slice. The Worker must define the behavior of omitted `step_inputs` and `{}` for invalid required-input requests. Successful optional-input idempotency fingerprint canonicalization should remain out of scope unless Judge explicitly accepts it as part of the slice.

### Review Edit Output-Contract Validation

- `backend/src/intric/flows/application/flow_run_service.py:942-960` passes `current_payload_json` directly to repository edit persistence.
- `backend/src/intric/flows/infrastructure/flow_run_repo.py:537-552` writes the edited payload to both checkpoint state and step result projection.
- `backend/src/intric/flows/runtime/output_runtime.py:96-117` already validates model-generated JSON/DOCX/PDF structured output against `output_contract`.

Codex recommendation: the review-edit slice must reuse or extract existing runtime validation behavior. A second ad hoc JSON-schema path would create future drift.

### Executor Failure Persistence

- `backend/src/intric/flows/runtime/executor.py:1184-1196` handles attempt-start failure with rollback, failed step persistence, and terminalization, but no local commit in that helper.
- `backend/src/intric/flows/runtime/executor.py:1255-1300` handles typed step failure similarly.
- `backend/src/intric/flows/runtime/executor.py:1316-1352` handles generic step failure similarly.
- `backend/src/intric/flows/runtime/executor.py:1354-1400` commits after successful step persistence.
- `backend/src/intric/flows/application/flow_run_terminalization.py:92-256` owns terminal run lifecycle, active result/attempt closure, rerun closure, checkpoint cancellation, and audit outbox.

Codex recommendation: keep this P0, but require a fresh-session red test before choosing the implementation shape. The fix may be a small executor failure-transition helper or a terminalizer API; do not decide before the red test proves the failure mode.

### Late Output After Terminalization

- `backend/src/intric/flows/runtime/executor.py:777-819` checks only `CANCELLED` after step execution before success persistence.
- `backend/src/intric/flows/runtime/executor.py:1365-1400` persists successful results and commits.
- `backend/src/intric/flows/infrastructure/flow_repo.py:585-591` uses unconditional `ON CONFLICT DO UPDATE` for step results.
- `backend/src/intric/flows/infrastructure/flow_repo.py:597-602` replaces result file rows after the upsert.
- `backend/src/intric/flows/application/flow_run_terminalization.py:109-126` and `backend/src/intric/flows/application/flow_run_terminalization.py:143-170` already treat terminalization races as no-op outcomes.

Codex recommendation: keep this as a separate P0. The likely owner is a repository-level atomic completion guard that prevents both result mutation and file-row replacement if the run/attempt/result is no longer active.

### Local Hygiene

- `backend/src/intric/flows/**/__pycache__` and `backend/tests/**/__pycache__` directories exist in the worktree. They are likely ignored cache artifacts, not source work, but they are a useful reminder that every commit must be staged intentionally.
- The current worktree also contains unrelated dirty/untracked files outside this goal. Scout must classify them before any Worker is allowed to stage.

## Added Board Requirements

1. Each P0 Worker must include a maintainability receipt:
   - canonical owner used,
   - why no new owner was created,
   - type-boundary impact,
   - public error behavior if API-visible,
   - comment quality / AI-slop check,
   - exact regression risk.

2. Cleanup must be more aggressive than production compatibility, but not casual:
   - grep proof,
   - behavior test replacing intended behavior,
   - fixture/migration cleanup if old shapes exist locally,
   - route/OpenAPI/API journey check when endpoint behavior changes.

3. Error handling must be reviewed as frontend/backend contract:
   - backend emits stable code, message, and context;
   - OpenAPI exposes examples for touched failures;
   - frontend has an understandable user-facing state after backend contract stabilizes;
   - API consumers can build web apps without reading backend source.

4. AI Builder maintainability should not be mixed into runtime P0s unless the same files are touched. Material-efficiency work should remain metric-backed and should not use `all_previous_steps` as a generic patch.

5. Claude iteration 1 tightened the board further:
   - every P0 needs a named red-test harness;
   - required-input validation and create-run idempotency fingerprint canonicalization must be separate unless Judge explicitly accepts the behavior change;
   - review-edit validation must directly reuse `output_processing.validate_against_contract`;
   - late-output protection must be repository-owned and atomic, not read-then-check;
   - Worker receipts must include new `Any`/`cast`/`type: ignore` counts and pasted changed comments;
   - cleanup Scout output must use a proof table rather than a loose list.

## What I Would Not Do First

- I would not start with broad comment cleanup. Remove slop comments in touched files; run a Scout before source-wide cleanup.
- I would not start with proposal-processor splitting. Split only after behavior pressure proves a narrower owner.
- I would not start with deleting fallback code before the public API golden journey exists, unless grep/tests prove a truly dead wrapper.
- I would not create a generic lifecycle engine. The current owner target is smaller: terminalizer plus explicit repository lifecycle methods.
