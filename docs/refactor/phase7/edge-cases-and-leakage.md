# Phase 7 Edge Cases And Leakage Audit

## TL;DR

The highest-risk leakage is policy and lifecycle state crossing boundaries as loose strings, raw request state, or JSON bags.
Flow/AI Builder needs typed policy actions, typed Celery commands, typed JSONB parsers, generated frontend API types, and one terminalization owner before feature work.
Pause/edit/resume and rerun must not reuse redispatch or optional fields to imply lifecycle.
Frontend state should consume generated API projections, not backend internals or manually duplicated schema.
No broad platform refactor is needed beyond shared dependencies touched for Flow/AI Builder boundaries.

## Boundary Leakage Cleanup

| Leakage | Evidence | Boundary leaking | Why it harms maintainability | Proposed canonical boundary | Acceptance criteria |
|---|---|---|---|---|---|
| Raw API-key scope state inside AI Builder router | `backend/src/intric/flows/ai_builder/ai_builder_router.py:180-210` reads `request.state.api_key_scope_type` and `api_key_scope_id`. | HTTP auth internals leak into route/application decisions. | Every route can reinterpret auth scope differently. | Typed `FlowApiAction` policy plus `FlowPrincipal`/scope filter dependency. | No Flow/AI Builder router reads raw `request.state.api_key_scope_*`. |
| String permission actions | `backend/src/intric/flows/api/flow_api_common.py:129-139` takes `required_access: str`; `:179-193` maps strings to helpers. | Policy contract leaks as string conventions. | New actions like review/rerun/resume can be misspelled or over-granted. | `FlowApiAction` enum/typed value with matrix tests. | Policy tests cover user, service key, AI Builder session, and legacy alias migration. |
| Pydantic HTTP payload exposes untyped runtime input | `backend/src/intric/flows/api/flow_models.py:431-435` exposes `input_payload_json: dict[str, Any]`, `step_inputs`, and top-level `file_ids`. | API schema leaks loose persistence/runtime shape. | External clients must infer canonical input mapping; top-level file IDs compete with per-step inputs. | `FlowRunCreateRequest` with typed input envelope and `step_inputs` only. | OpenAPI has no top-level run `file_ids`; generated client tests assert canonical shape. |
| Runtime state in JSON payload instead of relational mapping | `backend/src/intric/flows/application/flow_run_service.py:399-407` writes `step_inputs` and top-level `file_ids` into `input_payload_json`. | Request payload doubles as lifecycle/idempotency state. | Rerun/debug/audit of file-to-step mapping requires JSON inspection. | Relational `flow_run_step_input_files` plus typed evidence snapshot. | File associations query by run/step/file and idempotency fingerprint uses normalized relational-derived shape. |
| Celery payload as primitive parameter list | `backend/src/intric/flows/runtime/tasks.py:67-77` receives many separate IDs and retry fields. | Task boundary lacks one typed command. | Resume/rerun commands can drift and pass mutable state. | Pydantic/dataclass command payloads with IDs plus command metadata. | Celery tasks accept `FlowRunExecutionCommand`, `FlowRunResumeCommand`, and future `FlowStepRerunCommand`. |
| Terminalization split across executor/reconciliation | Executor updates status directly at `runtime/executor.py:716-731`; stale reconciliation fails runs in `runtime/tasks.py:322-358`. | Runtime lifecycle owner is duplicated. | Duplicate terminalization, crash recovery, and audit become caller-specific. | Application/runtime terminalization command. | Every terminal state change goes through one idempotent command and outbox policy. |
| Broad exception outer layers blur error taxonomy | AI Builder SSE catches broad `Exception` at `ai_builder_router.py:613-620`; Flow executor generic step catch at `runtime/executor.py:624-637`. | Domain/runtime failures leak into generic router/runtime handling. | Operators cannot distinguish invalid input, provider failure, task crash, and bug. | Failure taxonomy at runtime boundary; routers translate domain errors to API/SSE errors. | Named error codes for provider, validation, timeout, cancellation, stale revision, already resumed. |
| Frontend manual Flow API types | Manual Flow types start at `frontend/packages/intric-js/src/types/resources.d.ts:153`; generated schema exists separately. | Backend API schema duplicated manually on frontend. | Status/file mapping/schema changes drift silently. | Generated OpenAPI TypeScript schema plus narrow UI-only aliases. | Manual Flow runtime API blocks are removed or mapped to generated aliases. |
| Frontend evidence reads backend payload internals | `frontend/apps/web/src/lib/features/flows/flowEvidenceProvenance.ts:25-56` inspects `runtimeInput.file_ids` and `template_file_id`. | UI depends on internal payload keys, not API projection. | Deleting top-level `file_ids`/`template_file_id` breaks evidence UI indirectly. | Backend evidence view model/API projection. | Frontend evidence components read typed evidence fields, not raw runtime payload internals. |
| Permission aliases preserve old action semantics | Tests at `backend/tests/unittests/flows/test_flow_permissions.py:29-53` accept legacy flow aliases. | Permission migration leaks into active action model. | Review/resume/rerun could inherit broad grants accidentally. | Explicit migration map and typed policy matrix. | Legacy aliases map only to intended actions; no implicit review/resume/rerun. |
| AI Builder barrel hides model ownership | `backend/src/intric/flows/ai_builder/ai_builder_models.py:3-5` re-exports API/domain/event models. | API/domain/event contracts share a false owner. | Reviewers cannot see whether a type is HTTP schema, domain state, or event contract. | Canonical model modules by boundary. | Source/tests import API, domain, or event model modules directly. |

## Edge Case Matrix

| Edge case | Failure mode if ignored | Required owner |
|---|---|---|
| Duplicate resume request | Two workers resume same checkpoint and produce duplicate downstream outputs. | Review checkpoint CAS plus resume idempotency key. |
| Resume after run cancellation | Paused run becomes running after terminal state. | Terminalization command rejects non-active checkpoint/run status. |
| Worker crashes after checkpoint write before task return | Run remains waiting and resumable; no worker slot is needed. | Checkpoint transaction plus reconciliation ignores waiting runs. |
| Audit outbox insert fails during terminalization | Run terminalizes without durable audit. | Terminalization command fails before state change or writes compensating outbox by ADR. |
| Large number of paused runs | Polling scans all runs or misses stale checkpoints. | Indexed checkpoint table and status projection. |
| Step rerun after completed run | Final output still points at superseded downstream result. | Rerun operation invalidates/recomputes final projection. |
| Partial rerun with edited input | Idempotency key collides with original run or wrong edited file mapping. | Rerun-specific fingerprint includes root step and normalized edited inputs. |
| File valid for one step reused by another | Permissions/runtime input policy bypassed. | Step-scoped file validation and relational mapping. |
| Manual/generated type drift | Frontend compiles while API contract changes. | Generated type gate and wrapper tests. |
| Evidence export after cleanup | Historical evidence loses old lineage keys. | Versioned evidence parser/exporter preserves historical lineage while new requests use canonical shape. |

## Shared Dependencies Touched Because

| Shared dependency | Why it is in scope |
|---|---|
| Auth/scope dependencies | Flow/AI Builder need one policy entry point to avoid raw request-state reads. |
| Audit/outbox infrastructure | Flow terminal/review/rerun transitions need durable lifecycle audit. |
| OpenAPI generation and `intric-js` generated schema | Flow frontend state and client contracts must stop duplicating backend schemas. |
| Celery configuration/health | Flow runtime uses Celery tasks and reconciliation; ARQ must not be framed as an option for Flow. |
