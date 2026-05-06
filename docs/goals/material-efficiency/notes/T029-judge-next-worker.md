TL;DR:
T028 fixed the structured-field parse path, but the remaining E1 failures are still post-approval apply HTTP 500s.
The failed E1 artifacts include `approve.json` and no `apply.json`, so the public failure surface is `POST /plans/{plan_id}/apply`.
The artifacts do not contain the server stack rows for `b730ee9c` or `2ef2bcf3`; repo/tmp search only found the client-facing error files.
Do not change materializer behavior yet; first add typed phase-level apply telemetry that classifies compile vs execute and bounded materializer progress.
Claude green-lit the revised diagnostic Worker after requiring typed payloads, privacy tests, and reuse of the existing AI Builder telemetry pattern.

# T029 Judge Decision

## Problem

T028 made structured-field normalization shared between create and edit add-step parsing, and the relevant unit suite stayed green. The follow-up E1 live eval still had two HTTP 500s:

| Run | Status | Plan | Session | Evidence |
|---|---|---|---|---|
| E1 run 1 | `http_error` | `f54ae7cf-0d78-4a82-8487-3a9dac402c94` | `a1c71b1a-031b-443c-865b-b464c85e824a` | `/tmp/material-efficiency-live-eval/20260506-044605-t028-e1-edit-normalizer-retry/E1-run1/error.txt` |
| E1 run 2 | `http_error` | `8d6ee546-c63f-48cd-9d5a-33874e67af08` | `0c83090b-40ac-478f-af00-af86b56a9551` | `/tmp/material-efficiency-live-eval/20260506-044605-t028-e1-edit-normalizer-retry/E1-run2/error.txt` |
| E1 run 3 | `applied` | `e29390d9-ca67-4014-bf0e-4180fa99c757` | `cf6f8479-5db7-42ed-8c64-aa9e292ec87f` | `/tmp/material-efficiency-live-eval/20260506-044605-t028-e1-edit-normalizer-retry/E1-run3/apply.json` |

The failed runs include `approve.json` but no `apply.json`, which places the failure after plan approval and inside the apply path. They do not contain structured-field parser errors such as `Object fields must declare` or `self_correction_invalid_payload`.

## Evidence

- `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:142` wraps `compile_changeset` and `execute_changeset` in one `try`, so current logs cannot classify compile vs execute failures.
- `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:162` rolls the session back and re-raises, which is correct but loses AI Builder-specific context before the global 500 handler.
- `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:266` starts assistant creation before flow update, and `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:362` only compensates create-mode temporary flows, so edit-mode execute failures can be partial materializer failures.
- `backend/src/intric/server/main.py:356` and `backend/src/intric/server/main.py:430` mint user-facing 500 `error_id`s and log stack traces when retained, so T030 must not create a parallel error-id owner.
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:190` is the closest existing structured telemetry owner for AI Builder-specific operational events.

## Decision

`activate_worker`: T030 should add generic apply-failure telemetry before any behavior change.

This is a long-term reliability improvement because it gives every Flow AI Builder apply failure a typed, privacy-safe classification point. It is not tuned to C1/E1 and does not attempt to repair one generated flow.

## Selected Worker

Objective: add typed privacy-safe apply failure telemetry so post-approval AI Builder apply HTTP 500s can be classified by compile vs execute phase and bounded materializer progress without changing apply behavior.

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py`
- `backend/src/intric/flows/ai_builder/ai_builder_materializer.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_lifecycle.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_materializer.py`
- `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`
- `docs/goals/material-efficiency/notes/T030-apply-failure-telemetry.md`

Implementation constraints:

- Reuse the existing AI Builder telemetry module instead of inline dict payloads.
- Add an apply-specific log key and schema version instead of reusing proposal names literally.
- Use typed payload models with `extra="forbid"` as the privacy fence.
- Split `apply_plan` failure handling by `compile_changeset` and `execute_changeset`; do not infer phase from exception type.
- Add only an optional synchronous materializer progress callback; do not change materializer behavior or compensation semantics.
- Keep global 500 `error_id` ownership in the server exception handler.

## Acceptance Criteria

- Compile failures log `phase="compile_changeset"` with exception class and optional `BadRequestException.code`.
- Execute failures log `phase="execute_changeset"` with changeset counts and the last bounded materializer progress snapshot.
- Telemetry payload JSON never contains raw prompts, flow spec JSON, input bindings, source material, or document/audio contents.
- Existing session rollback behavior remains unchanged.
- Live eval is rerun after local verification, and any new HTTP 500s are classified from the new event when backend logs are available.

## Tests Required

- Red test: compile `RuntimeError` logs compile phase and rolls back.
- Red test: compile `BadRequestException` logs compile phase and code.
- Red test: execute `RuntimeError` logs execute phase, changeset counts, progress, and rolls back.
- Red test: execute `BadRequestException(code="stale_revision")` logs execute phase and code.
- Red test: sensitive prompt/binding/source substrings are absent from `model_dump_json()`.
- Materializer callback test: progress snapshots are emitted in order with bounded count/stage fields only.

## Risk / Trade-Off

This slice does not fix the HTTP 500 directly. That is intentional: without a stack trace or phase classification, changing materializer behavior risks patching the wrong layer. The trade-off is one diagnostic slice before a behavior slice, but it makes the next Worker deterministic and reviewable.

Confidence: high.
