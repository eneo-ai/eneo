# Phase 1 Agent E: API Consumer Review

TL;DR:
1. The current public Flow API supports the basic external developer loop: discover a published flow, inspect runtime contract, upload files, start a run, poll, list step outputs, download artifacts, and export evidence.
2. Advanced workflow support is not first-class: per-step file mapping is expressible only as an underspecified `StepRunInput`, step-level rerun is absent, and human review/edit/resume has no runtime lifecycle state.
3. The main API contract risk is not missing endpoints; it is split ownership across backend Pydantic schemas, JSONB payloads, handwritten `intric-js` types, generated OpenAPI types, frontend runtime helpers, and DB CHECK constraints.
4. The highest-ROI low-risk work is to make generated `schema.d.ts` the frontend contract source for Flow runtime types and delete overlapping hand-written `resources.d.ts` Flow run shapes.
5. Do not build a generic `RunControl` endpoint; split contract typing, lifecycle states, review/edit/resume, and rerun into separately reviewable slices.

## Scope And Standard

This review covers the public flow API surface an external webapp would consume: authentication and scope behavior, flow discovery, published runtime definition inspection, inputs, uploads, file mapping, run start, polling, step outputs, final results, evidence/artifacts, pause/review/edit/resume/rerun gaps, error behavior, idempotency, OpenAPI, and generated/handwritten client usability.

Relevant standards:

| Standard | Applied Rule |
|---|---|
| API consumer standard | External developers should understand authenticate, list, inspect definitions, upload/attach files, start work, poll status, retrieve outputs/artifacts/evidence, pause/edit/resume/retry, and handle errors without reading backend source. |
| API maintainer standard | Every endpoint needs a clear owner for path, operation ID, request/response model, status codes, error shape, authorization, idempotency, and generated client impact. |
| Typed boundary standard | Public request/response contracts should be typed at the HTTP boundary; broad JSON bags need a named owner and migration behavior. |
| Single-source-of-truth standard | Runtime statuses, schema types, error codes, and frontend client types should have one canonical owner, not parallel hand-written shapes. |

## External Developer Journey

| Journey Step | Current Endpoint / Client | Request Schema | Response Schema | Missing Docs / Confusing Naming / SDK Quality / Error Behavior |
|---|---|---|---|---|
| Authenticate / authorize | Global router includes `/flows` with `require_resource_permission_for_method("flows")` and API key scope check using path param `id` at `backend/src/intric/server/routers.py:392-399`. | Auth is dependency-owned, not flow schema-owned. | Error examples use `GeneralError` through `error_response` in route definitions. | Good: flow-level API key scope is central, and the docs site has a basic integration sequence at `frontend/apps/docs-site/src/content/guides/flows-api-guide.mdx:100-111`. Gap: review/edit/resume/rerun and idempotency retention are not yet documented as public API contracts. |
| List flows | `GET /api/v1/flows/?space_id=...` in `backend/src/intric/flows/api/flow_authoring_router.py:166-229`; JS client `flows.list` at `frontend/packages/intric-js/src/endpoints/flows.js:156-165`. | Query: `space_id`, `limit`, `offset` at `flow_authoring_router.py:188-199`. | `PaginatedResponse[FlowSparsePublic]` at `flow_authoring_router.py:166-170`; `FlowSparsePublic` fields at `backend/src/intric/flows/api/flow_models.py:348-365`. | Consumer DX issue: description says `count` is current page count, not total, at `flow_authoring_router.py:172-176`; this prevents robust pagination unless clients infer "has more" by `items.length == limit`. |
| Inspect draft definition | `GET /api/v1/flows/{id}/` at `flow_authoring_router.py:232-281`; JS client `flows.get` at `flows.js:168-175`. | Path `id`. | `FlowPublic` includes `steps: list[FlowStepPublic]` at `flow_models.py:368-374`. | This is user-principal-oriented draft data, not a published runtime contract; the description says so at `flow_authoring_router.py:238-242`. External service-key consumers should use the published runtime view instead. |
| Inspect published runtime view | `GET /api/v1/flows/{id}/published/` at `flow_authoring_router.py:284-330`; runtime paths assembled at `backend/src/intric/flows/api/flow_assembler.py:47-75`. | Path `id`. | `FlowRuntimePublic` with `runtime_paths` at `flow_models.py:394-407`. | Good: runtime paths discover every major flow-run URL (`flow_assembler.py:55-72`). Gap: JS client has no `flows.published` method in `flows.js:133-575`; consumers using the package must know the URL or use generated schema directly. |
| Understand run inputs | `GET /api/v1/flows/{id}/run-contract/` at `flow_upload_router.py:22-81`; JS client `flows.runContract.get` at `flows.js:240-248`. | Path `id`. | `FlowRunContractPublic` includes `published_flow_version`, `form_fields`, `steps_requiring_input`, `aggregate_max_files`, and `template_readiness` at `flow_models.py:668-684`. | Good: this is the canonical entry point for rendering a run form. Gap: `FormFieldPublic` allows extra fields at `flow_models.py:657-665`, so form field schema remains flexible rather than contract-tight. |
| Understand upload policy | `GET /api/v1/flows/{id}/input-policy/` at `flow_upload_router.py:84-146`; JS client `flows.inputPolicy` at `flows.js:231-238`. | Path `id`. | `FlowInputPolicyPublic` at `flow_models.py:469-495`. | Issue: `recommended_run_payload` is `dict[str, Any]` at `flow_models.py:495`; this is helpful as prose-like guidance but weak as a generated SDK contract. |
| Upload flow-level files | `POST /api/v1/flows/{id}/files/` at `flow_upload_router.py:149-266`; JS client `flows.files.upload` at `flows.js:339-353`. | Multipart `upload_file` at `flow_upload_router.py:154-170`. | `FilePublic`. | Good: route documents flow-first validation and machine codes for upload errors at `flow_upload_router.py:172-219`. Gap: flow-level files are legacy-compatible with first-step input only, as runtime falls back to top-level `file_ids` only for step 1 at `step_input_resolution.py:391-403`. |
| Upload step runtime files | `POST /api/v1/flows/{id}/steps/{step_id}/runtime-files/` at `flow_upload_router.py:269-380`; JS client `flows.steps.runtimeFiles.upload` at `flows.js:320-335`. | Multipart `upload_file`, path `step_id`. | `FilePublic`. | Good: per-step upload exists. Gap: run submission only carries file IDs, not roles, labels, or caller intent, because `StepRunInput` only has `file_ids` at `flow_models.py:410-411`. |
| Map files to inputs/steps | `FlowRunCreateRequest.step_inputs: dict[UUID, StepRunInput]` at `flow_models.py:414-434`; create router maps Pydantic `StepRunInput` into dictionaries at `flow_run_execution_router.py:171-186`. | `StepRunInput.file_ids` at `flow_models.py:410-411`, plus legacy top-level `file_ids` at `flow_models.py:431-434`. | Persisted inside `input_payload_json` by `FlowRunService.create_run` at `flow_run_service.py:399-407`. | Per-step mapping is partly expressible today. It is underspecified, not absent: no role, label, per-file purpose, or stable typed file association object beyond a list of UUIDs. |
| Start run | `POST /api/v1/flows/{id}/runs/` at `flow_run_execution_router.py:106-204`; JS client `flows.runs.create` at `flows.js:412-448`. | `FlowRunCreateRequest` at `flow_models.py:414-434`; optional `Idempotency-Key` header at `flow_run_execution_router.py:150-156`. | `FlowRunPublic` at `flow_models.py:445-467`. | Good: idempotency is implemented and documented at `flow_run_execution_router.py:45-49`. Risk: run payload remains broad (`input_payload_json: dict[str, Any]`, `output_payload_json: dict[str, Any]`) at `flow_models.py:461-462`. |
| Idempotent retries | `Idempotency-Key` is accepted at `flow_run_execution_router.py:150-156`; duplicate key with different fingerprint raises `flow_run_idempotency_conflict` at `flow_run_service.py:437-451`. | Caller-provided header. | Existing run returned for same fingerprint. | Good for create-run retry. Gaps: fingerprint hashes only `flow_id`, `flow_version`, and `input_payload_json` at `flow_run_service.py:492-510`, and repo lookup has no TTL/expiry predicate at `flow_run_repo.py:137-153`; rerun must define its own idempotency scope and retention semantics. |
| Poll status / final result | `GET /api/v1/flows/{id}/runs/{run_id}/` at `flow_run_execution_router.py:263-302`; JS client `flows.runs.get` at `flows.js:477-487`. | Path `id`, `run_id`. | `FlowRunPublic.status` and `output_payload_json` at `flow_models.py:445-467`. | Good enough for polling. Gap: statuses are closed to queued/running/completed/failed/cancelled at `backend/src/intric/flows/enums.py:64-69`; no paused-for-human vs paused-for-error state exists. |
| List runs | `GET /api/v1/flows/{id}/runs/` at `flow_run_execution_router.py:207-260`; JS client `flows.runs.list` at `flows.js:465-475`. | Query `limit`, `offset`. | `PaginatedResponse[FlowRunPublic]`. | Same pagination issue as list flows: `count` is current page count at `flow_run_execution_router.py:80-85`. |
| Receive step events / inspect step output | No streaming event endpoint in the flow public surface. Poll step outputs via `GET /api/v1/flows/{id}/runs/{run_id}/steps/` at `flow_run_steps_router.py:76-138`; JS client `flows.runs.steps` at `flows.js:489-498`. | Path `id`, `run_id`. | `list[FlowRunStepPublic]` at `flow_run_steps_router.py:76-82`; schema at `flow_models.py:498-528`. | Consumer gap: "receive step events" is polling-only today. `FlowRunStepPublic.diagnostics` is `list[dict[str, Any]]` at `flow_models.py:521-523`, so client handling of step diagnostics is not type-guided. |
| Graph / topology | `GET /api/v1/flows/{id}/graph/?run_id=...` at `flow_run_steps_router.py:141-228`; JS client `flows.graph` at `flows.js:218-229`. | Optional `run_id`. | `GraphResponse`. | Good: can inspect live or run-pinned graph. Gap: graph node status is separate from step result shape and should use generated runtime types if exposed to consumers. |
| Get artifacts | `POST /api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/` at `flow_run_steps_router.py:231-320`; JS client `runs.artifactSignedUrl` at `flows.js:553-575`. | `SignedURLRequest`. | `SignedURLResponse`. | Good: artifact ID is checked against actual step outputs at `flow_run_service.py:727-758`. Gap: artifacts themselves live inside broad `output_payload_json` structures at `flow_models.py:512-513` and are hand-typed in frontend at `resources.d.ts:278-293`. |
| Get evidence | `GET /api/v1/flows/{id}/runs/{run_id}/evidence/` at `flow_run_evidence_router.py:66-135`; JS client `runs.evidence` at `flows.js:525-535`. | Path `id`, `run_id`. | `FlowRunEvidenceResponse` at `flow_models.py:1044-1061`. | Good: evidence has a dedicated route and audit-required 503 behavior at `flow_run_evidence_router.py:87-93`. Gap: `definition_snapshot` is `dict[str, Any]` at `flow_models.py:1057-1059`. |
| Export evidence | `GET /api/v1/flows/{id}/runs/{run_id}/evidence/export` at `flow_run_evidence_router.py:138-251`; JS client `runs.exportEvidence` at `flows.js:537-550`. | Query `format`, `detail`, `reason` at `flow_run_evidence_router.py:187-201`. | Declared `FlowRunEvidenceExportResponse`, but endpoint returns a raw `Response` attachment at `flow_run_evidence_router.py:246-250`. | SDK mismatch risk: OpenAPI says JSON response schema, implementation returns attachment headers. Decide whether this is a JSON API response or download endpoint and align generated clients. |
| Cancel run | `POST /api/v1/flows/{id}/runs/{run_id}/cancel/` at `flow_run_execution_router.py:305-360`; JS client `runs.cancel` at `flows.js:500-510`. | No body. | `FlowRunPublic`. | Cancel is the only end-user run-control endpoint besides stale queued redispatch. Service behavior is idempotent for terminal runs and cancels pending/running step results at `flow_run_service.py:677-688`; public docs should spell out queued/running/terminal semantics. |
| Retry / resume / rerun | `POST /api/v1/flows/{id}/runs/{run_id}/redispatch/` exists at `flow_run_execution_router.py:363-442`; JS client `runs.redispatch` at `flows.js:512-523`. | No body. | `FlowRunRedispatchResponse` at `flow_models.py:530-536`. | Redispatch is explicitly stale-queued only (`flow_run_execution_router.py:369-376`), not step-level rerun or resume. Response exposes `redispatched_count` even though endpoint passes `limit=1` at `flow_run_execution_router.py:416-421`. |

## API Consumer DX Score

| Question | Score | Evidence / Rationale |
|---|---:|---|
| Can a developer understand the basic API without reading backend code? | 6 | Route descriptions are unusually detailed for run creation (`flow_run_execution_router.py:51-69`) and contract discovery (`flow_upload_router.py:28-39`), and the docs site covers the happy-path sequence (`flows-api-guide.mdx:100-111`). Gaps remain: `flows.js` lacks the published runtime endpoint, and advanced lifecycle/idempotency-retention behavior is not contract-documented. |
| Can a usable TS client be generated? | 5 | Generated `schema.d.ts` includes endpoint operations and schemas (`schema.d.ts:33622-33711`, `schema.d.ts:33919-34143`), but the shipped `resources.d.ts` hand-types overlapping Flow runtime concepts at `resources.d.ts:295-366` instead of re-exporting generated schemas. |
| Can clients handle errors safely? | 6 | Many endpoints declare machine-readable `GeneralError` examples, e.g. create-run 400/403/404 at `schema.d.ts:33650-33708`; however validation errors still use generic `HTTPValidationError` (`schema.d.ts:33701-33708`), and evidence export has response-shape mismatch risk. |
| Can clients build advanced workflows? | 3 | Per-step file mapping is only a UUID-list contract, rerun/pause/review/edit/resume are not first-class endpoints, and runtime statuses lack human-review states. |
| Overall API consumer DX | 5 | The happy path is usable, but advanced workflow gaps require source reading and coordinated schema/runtime/data-model changes. |

## User Story 1: Per-Step File Mapping

**Story:** External webapp uploads 6 files. Files 1-3 map to step 3; files 4-6 map to steps 4, 6, and 8.

### Current Answer

Partly possible today.

The backend has step-scoped upload (`POST /flows/{id}/steps/{step_id}/runtime-files/`) at `flow_upload_router.py:269-380`, and run creation accepts `step_inputs: dict[UUID, StepRunInput]` at `flow_models.py:431-434`. `StepRunInput` is typed but minimal: only `file_ids: list[UUID]` at `flow_models.py:410-411`. Runtime resolution checks step-specific `step_inputs[str(step.step_id)].file_ids` before falling back to top-level `file_ids` for step 1 only at `step_input_resolution.py:391-403`.

The current request can express this shape:

```json
{
  "expected_flow_version": 7,
  "step_inputs": {
    "step-3-uuid": { "file_ids": ["file-1", "file-2", "file-3"] },
    "step-4-uuid": { "file_ids": ["file-4"] },
    "step-6-uuid": { "file_ids": ["file-5"] },
    "step-8-uuid": { "file_ids": ["file-6"] }
  }
}
```

But it is weak for consumer DX because the association is an unlabelled list of file IDs. The contract cannot express roles such as "source transcript", "supporting PDF", "template attachment", or "same files as prior run"; it also cannot carry a display label for UI review.

### Clean Minimal Schema

Do not create a parallel request shape. Extend the existing `StepRunInput` canonical owner in `backend/src/intric/flows/api/flow_models.py:410-411`:

```python
class StepRunFileInput(BaseModel):
    file_id: UUID
    role: str | None = None
    display_label: str | None = None

class StepRunInput(BaseModel):
    file_ids: list[UUID] = Field(default_factory=list)
    files: list[StepRunFileInput] = Field(default_factory=list)
```

Compatibility rule: accept `file_ids` as the compact form, normalize to `files` internally, and keep the existing top-level `file_ids` adapter documented until persisted queued runs and external consumers no longer depend on it. The legacy adapter is load-bearing today because `FlowRunService.create_run` calls `apply_legacy_step_one_adapter` at `flow_run_service.py:385-390`, and runtime still resolves top-level `file_ids` for step 1 at `step_input_resolution.py:401-402`. Deletion trigger: remove the adapter only after no queued/running persisted run contains top-level `file_ids`, no public docs/examples mention the legacy shape, and API access logs show no external `POST /runs/` legacy usage for a defined window such as 30 days.

### Required Changes

| Area | Proposed Change | Evidence / Owner |
|---|---|---|
| Request schema | Extend `StepRunInput`; do not create a second run-input schema. | Canonical schema owner is `flow_models.py:410-434`. |
| Runtime input resolver | Add a named normalizer such as `normalize_step_file_associations` in `step_input_resolution.py` to convert `file_ids` and `files` into one internal step-file map before `_resolve_runtime_requested_ids`. | Current resolver reads `step_inputs` and top-level `file_ids` at `step_input_resolution.py:391-403`. |
| FlowRunService | Keep `apply_legacy_step_one_adapter` as a documented compat adapter; add deprecation criteria, not immediate deletion. | Adapter is called at `flow_run_service.py:385-390`; persisted payload stores both `step_inputs` and `file_ids` at `flow_run_service.py:399-407`. |
| Frontend/client | Generate or re-export `StepRunInput` from `schema.d.ts`; remove manual `FlowRunStepInputs = Record<string, { file_ids: string[] }>` when the richer shape lands. | Manual type exists at `resources.d.ts:313`; generated schema has `FlowRunCreateRequest.step_inputs` at `schema.d.ts:11884-11890`. |
| Migration impact | No DB migration for additive request fields, but persisted `input_payload_json` remains JSONB and needs a versioned payload parser if historical runs are interpreted after schema changes. | JSONB storage at `flow_tables.py:372-377`; response broad payload at `flow_models.py:461-462`. |

### Acceptance Criteria

- [ ] `StepRunInput` supports both compact `file_ids` and self-describing `files`.
- [ ] Runtime validates that every listed file belongs to the caller and matches the step runtime-input policy.
- [ ] Top-level `file_ids` still works for existing queued runs and documented legacy clients until an explicit deletion condition and date are recorded.
- [ ] Generated client types expose the same shape as the backend schema.
- [ ] Public examples show mapping multiple files to non-contiguous steps.

### Tests Required

| Test | Layer | Behavior Protected |
|---|---|---|
| Per-step multi-file run contract test | API contract/integration | Upload files to steps 3, 4, 6, and 8; create run; assert `input_payload_json.step_inputs` persists normalized file associations. |
| Runtime resolver behavior test | Unit/integration | For a run with step-scoped files, each step only receives its assigned files; step 1 legacy top-level `file_ids` still resolves. |
| Generated-client drift test | Frontend package/type check | `FlowRunCreateRequest` and `StepRunInput` come from generated schema or a narrow re-export, not a parallel handwritten type. |

Risk/trade-off: keeping `file_ids` and adding `files` temporarily preserves compatibility but creates two accepted input shapes. Mitigate with one canonical normalized internal representation and a documented deletion condition. Confidence: high.

## User Story 2: Step-Level Execution / Rerun

**Story:** External webapp wants to rerun only step 5 of a completed run with edited input, without rerunning steps 1-4.

### Current Answer

Not possible today.

The public run-control surface has cancel at `flow_run_execution_router.py:305-360` and stale queued redispatch at `flow_run_execution_router.py:363-442`. Redispatch is explicitly scoped to stale queued runs at `flow_run_execution_router.py:369-376`; it calls `redispatch_stale_queued_runs(..., limit=1)` at `flow_run_execution_router.py:416-421`. Step results are listed and claimable internally, but there is no public endpoint for editing a step input, invalidating downstream results, or rerunning a step.

The data model currently stores one current result per run/step with `UniqueConstraint("flow_run_id", "step_id")` at `flow_tables.py:519-521`, and attempts are separate historical rows keyed by `(flow_run_id, step_id, attempt_no)` at `flow_tables.py:586-590`. That is enough to record a new attempt, but not enough to model a public rerun lifecycle without explicit invalidation and audit semantics.

### Clean Design

Do not overload redispatch. Create a separate step-rerun contract:

```http
POST /api/v1/flows/{flow_id}/runs/{run_id}/steps/{step_id}/rerun/
Idempotency-Key: flow-step-rerun:<caller-stable-key>

{
  "expected_run_updated_at": "2026-04-28T12:34:56Z",
  "input_payload_json": { "text": "edited input for step 5" },
  "step_inputs": { "step-5-uuid": { "files": [{ "file_id": "..." }] } },
  "rerun_from_step": true
}
```

Response should not be a count. Use an explicit object:

```json
{
  "run": { "...": "FlowRunPublic" },
  "rerun": {
    "step_id": "...",
    "step_order": 5,
    "attempt_no": 2,
    "invalidated_step_orders": [5, 6, 7, 8]
  }
}
```

### Required Changes

| Area | Proposed Change | Evidence / Owner |
|---|---|---|
| API | Add a dedicated step-rerun endpoint under run steps, not under redispatch. | Existing step output route owner is `flow_run_steps_router.py:76-138`; redispatch is stale-queued only at `flow_run_execution_router.py:363-442`. |
| Application behavior | Add `FlowRunService.rerun_step(...)` with transaction ownership: verify access, verify run terminal/rerunnable, write new attempt, reset selected `FlowStepResults`, persist edited input, enqueue execution. | Current lifecycle owner is `FlowRunService` (`flow_run_service.py:325-490`, `flow_run_service.py:574-688`). |
| Runtime | Executor must support start-at-step and use persisted prior completed results for steps 1-4. | Current executor/repo claiming assumes queued/running whole-run lifecycle; repo active statuses are only queued/running at `flow_run_repo.py:40`. |
| Data model | Keep current result row per step, append attempt rows, and add explicit invalidation metadata or audit records for downstream steps. | Current result and attempt uniqueness at `flow_tables.py:519-521`, `flow_tables.py:586-590`. |
| Idempotency | Define rerun idempotency separately from create-run. Do not reuse parent run key. | Create-run idempotency returns the existing run for matching key/fingerprint at `flow_run_service.py:437-451`; fingerprint excludes parent run/step/attempt at `flow_run_service.py:492-510`. |
| Frontend | Add generated SDK method and UI affordance after backend contract exists; do not add a mock frontend-only rerun state. | Current frontend only redispatches stale queued runs via `FlowRunsTable.svelte:239-248`. |
| Audit | Add `FLOW_RUN_STEP_RERUN_REQUESTED`, `FLOW_RUN_STEP_OUTPUT_EDITED`, and downstream invalidation audit actions before endpoint work. | Existing audit actions stop at create/completed/failed/redispatched/cancelled/artifact/evidence in `action_types.py:81-93`. |

### Acceptance Criteria

- [ ] Rerun endpoint rejects active runs unless the design explicitly supports pausing first.
- [ ] Rerun endpoint names whether downstream steps are invalidated, reused, or rerun.
- [ ] Idempotency key collision with the original create-run cannot return the parent run by mistake.
- [ ] Step attempts show prior and rerun attempts in order.
- [ ] Public response tells consumers which outputs remain valid.

### Tests Required

| Test | Layer | Behavior Protected |
|---|---|---|
| Completed-run step 5 rerun | API integration + worker/runtime | Steps 1-4 remain completed and reused; step 5 gets new attempt; downstream policy is explicit. |
| Idempotent rerun retry | API contract | Same rerun key returns same rerun operation; different body with same key returns rerun-specific conflict. |
| Permission denial | API integration | Non-owner/service key cannot rerun another principal's run unless policy explicitly permits. |
| Audit test | Integration | Rerun requested, output edited, and downstream invalidation events are written with run/step/attempt IDs. |

Risk/trade-off: step-level execution has the highest blast radius because it changes runtime lifecycle semantics, data validity, idempotency, and UI expectations. Ship after the contract/type slice and after a state-machine ADR. Confidence: high that it is absent today; medium on exact endpoint shape until runtime reviewer and data-model reviewer findings are reconciled.

## User Story 3: Human-In-The-Loop Pause/Edit/Resume

**Story:** Step 1 speech-to-text -> user reviews/edits transcript -> step 2 LLM summary -> user edits summary -> step 3 template fill.

### Current Answer

Not possible as a public runtime primitive today.

Runtime run statuses are closed to queued, running, completed, failed, and cancelled at `enums.py:64-69`; step result statuses are closed to pending, running, completed, failed, and cancelled at `enums.py:72-77`; DB CHECK constraints duplicate those values at `flow_tables.py:397-400` and `flow_tables.py:503-506`. Step attempts are also closed to started/retried/failed/completed/cancelled at `flow_tables.py:570-572`. There is no `pending_review` / `awaiting_review` state, no edit-step-output endpoint, and no resume endpoint in the router aggregators (`flow_run_router.py:25-42` exports create/list/get/cancel/redispatch/evidence/steps/graph/artifact only).

### Required Primitives

| Primitive | Proposed Shape | Why It Matters |
|---|---|---|
| Definition flag | Step definition needs `review_policy` or `review_checkpoint` in published `definition_json`. | Without a definition-level owner, runtime cannot know which steps pause and which outputs are editable. |
| Run status | Add `awaiting_review` to `FlowRunStatus`. | Distinguishes healthy human pause from worker failure or cancellation. |
| Step status | Add `awaiting_review` to `FlowStepResultStatus`. | Identifies which step needs review. |
| Review item | Persist review metadata: run, step, attempt, editable output payload, reviewer, submitted_at, resumed_at. | Avoids hiding review state in `output_payload_json`. |
| Edit API | `PATCH /flows/{flow_id}/runs/{run_id}/steps/{step_id}/output/` or `POST .../reviews/{review_id}/edits/`. | Makes edited transcript/summary a first-class auditable change. |
| Resume API | `POST /flows/{flow_id}/runs/{run_id}/resume/` with expected review revision. | Prevents resume races and stale edits. |
| Permission | Add `flow.review` / `flow.resume` or equivalent scope policy. | Review/edit is not the same as run/create/view. |
| Audit | Add review requested, output edited, resume requested, review skipped/cancelled actions. | Current audit action enum does not include review/pause/resume/rerun actions (`action_types.py:81-93`). |

### Migration Impact

| Surface | Required Change | Evidence |
|---|---|---|
| Enum | Add review state(s) to backend runtime enums. | `FlowRunStatus` at `enums.py:64-69`; `FlowStepResultStatus` at `enums.py:72-77`. |
| DB constraints | Update run, result, and possibly attempt CHECK constraints. | `flow_tables.py:397-400`, `flow_tables.py:503-506`, `flow_tables.py:570-572`. |
| Indexing/reconciliation | Add a partial index or reconciler rule for review states; existing stale-running index only covers `status = 'running'`. | `flow_tables.py:439-444`; stale-running reconciler at `flow_run_service.py:655-675`; repo query filters running only at `flow_run_repo.py:225-241`. |
| Frontend types | Replace manual unions before adding states, or every state addition must edit multiple handwritten types. | `resources.d.ts:295-366` duplicates Flow run and step result status unions; generated enum exists at `schema.d.ts:12924-12927`. |
| Generated API | Add named operation IDs and schemas for review/edit/resume. | Current operations include create/list/get/cancel/redispatch/evidence/steps in `schema.d.ts:33622-34143`; no review/resume/rerun operations are generated. |

### Acceptance Criteria

- [ ] Published flow definitions explicitly say which step pauses and what output is editable.
- [ ] Runtime status distinguishes `awaiting_review` from failed/cancelled.
- [ ] Only one pending review per run/step/attempt is active unless multi-review is explicitly designed.
- [ ] Edited output is versioned and auditable; original output is retained.
- [ ] Resume validates the expected review revision and refuses stale resume.
- [ ] External API consumers can poll and render the required human action without reading backend source.

### Tests Required

| Test | Layer | Behavior Protected |
|---|---|---|
| Speech-to-text review journey | E2E/API + worker | Step 1 completes, run enters `awaiting_review`, edit transcript, resume, step 2 receives edited transcript. |
| Summary review journey | E2E/API + worker | Step 2 pauses, edited summary persists, step 3 template fill receives edited summary. |
| Stale resume conflict | API contract | Resume with old review revision fails with machine-readable conflict. |
| Permission matrix | API integration | Viewer cannot edit/resume; authorized reviewer can; service key behavior is explicit. |
| Crash recovery | Runtime integration | Worker crash while awaiting review does not mark run failed; reconciler does not redispatch paused review work. |

Risk/trade-off: this is a state-machine/data-model feature, not an endpoint-only feature. It should not be bundled with step rerun. Confidence: high.

## Canonical Contract Owners

| Concept | Existing Locations | Problem | Proposed Canonical Home | Merge/Delete Path |
|---|---|---|---|---|
| Flow runtime HTTP schemas | `backend/src/intric/flows/api/flow_models.py:377-435`, `flow_models.py:445-528`, `flow_models.py:632-684`, `flow_models.py:1044-1064` | One large schema module owns authoring, runtime, graph/evidence/debug, and template concepts; still the current HTTP schema owner. | Keep `flow_models.py` as the HTTP schema owner short term; later split by domain-specific modules only if split improves locality and generated names. | Do not add a new `types` or `helpers` module. Add typed nested models in place first; split only with route/module boundary. |
| Run lifecycle behavior | `backend/src/intric/flows/application/flow_run_service.py:325-490`, `flow_run_service.py:517-835` | Service owns create/list/cancel/evidence, but future rerun/review behavior would make it larger. | `FlowRunService` remains application owner; introduce smaller domain functions only where they protect invariants, not pass-through services. | Do not create a one-method rerun manager. Add behavior-focused methods with transaction boundaries. |
| Runtime file resolution | `flow_run_service.py:385-390`, `backend/src/intric/flows/runtime/step_input_resolution.py:54-388`, `step_input_resolution.py:391-403` | File mapping logic is split between create-run normalization and runtime resolution. | `StepRunInput` schema plus a named `normalize_step_file_associations` function in `step_input_resolution.py` that normalizes one canonical step-file map. | Keep the step-1 legacy adapter until persisted payload and external consumer evidence says it can be removed. |
| Runtime statuses | Backend enum `enums.py:64-85`, DB constraints `flow_tables.py:397-400`, `flow_tables.py:503-506`, `flow_tables.py:570-572`, frontend manual types `resources.d.ts:295-366`, generated enum `schema.d.ts:12924-12927` | Status values are duplicated across backend, DB, generated types, and handwritten TS unions. | Backend enum + DB migration are source of runtime truth; generated OpenAPI types should be the frontend source. | Delete manual Flow run/status unions in `resources.d.ts` after re-exporting generated types. |
| Frontend Flow runtime types | `frontend/packages/intric-js/src/types/resources.d.ts:241-366`, generated `schema.d.ts:11844-11890`, `schema.d.ts:12924-13054` | Handwritten Flow runtime types overlap generated schemas with different optionality and broad `Record<string, unknown>`. | Generated `schema.d.ts` components, re-exported narrowly from `resources.d.ts` where package ergonomics require it. | Use the existing generated re-export pattern seen elsewhere in `resources.d.ts`; delete overlapping hand types. |
| Redispatch result | `flow_models.py:530-536`, `flow_run_execution_router.py:416-442`, frontend use at `FlowRunsTable.svelte:239-248` | Public response says count, but flow-first endpoint requests at most one redispatch. | Response should be honest: `redispatched: bool`, `reason: str | None`, `run: FlowRunPublic`. | Pre-prod: break the API now and update the two tests/client callers; do not mirror count-based shape for rerun. |
| Evidence export response | `flow_run_evidence_router.py:138-251`, `flow_models.py:1064-1301`, generated operation `schema.d.ts:34007-34121` | OpenAPI declares JSON schema but implementation returns `Response` with attachment header. | Decide owner: JSON API response or download endpoint. If download, document content type/header and adapt generated client expectations. | Do not keep schema and attachment semantics divergent. |

## Top Gaps And Findings

### Finding 1: Runtime contracts are split between typed schemas and broad JSON payloads

| Field | Detail |
|---|---|
| Problem | Public schemas expose typed shells, but the most important runtime values are still `dict[str, Any]` / `Record<string, unknown>`, and the input-policy recommendation payload is untyped. |
| Why it matters | External consumers cannot safely understand input/output payloads, evidence snapshots, diagnostics, or artifacts from generated types alone. |
| Evidence | `FlowRunPublic.input_payload_json` and `output_payload_json` are `dict[str, Any]` at `flow_models.py:461-462`; `FlowInputPolicyPublic.recommended_run_payload` is `dict[str, Any]` at `flow_models.py:495`; `FlowRunStepPublic.input_payload_json`, `output_payload_json`, `model_parameters_json`, and diagnostics are broad dictionaries at `flow_models.py:512-523`; `FlowRunEvidenceResponse.definition_snapshot` is `dict[str, Any]` at `flow_models.py:1057-1059`; DB stores run/result JSONB dictionaries at `flow_tables.py:372-377` and `flow_tables.py:473-480`. |
| Current owner | `backend/src/intric/flows/api/flow_models.py` for HTTP; SQLAlchemy tables for persistence; runtime packages for interpretation. |
| Proposed canonical home | Versioned runtime contract models under the HTTP schema owner plus parser/normalizer functions in runtime input/output modules. |
| Merge/delete path | Replace ad hoc frontend `Record<string, unknown>` Flow runtime types with generated schema re-exports; introduce typed nested payloads incrementally for artifacts, diagnostics, runtime input metadata, and evidence snapshot metadata. |
| Acceptance criteria | Generated client exposes typed artifacts, diagnostics, run output, and step output; broad JSON remains only for deliberately user-defined structured output. |
| Tests required | API contract tests for generated schemas; backend serialization tests for artifacts/diagnostics/evidence; frontend type tests compiling against generated types. |
| Risk/trade-off | Over-typing user-defined structured LLM output would be wrong; keep that as an explicit `JsonValue` escape hatch while typing platform-owned fields. |
| Human reviewability impact | Reviewers can see whether a change modifies the public contract or only user data, instead of reading broad JSON conventions. |
| Confidence | High. |

### Finding 2: Low-risk consumer contract gaps should be fixed before larger lifecycle work

| Field | Detail |
|---|---|
| Problem | Several small public-contract gaps are already visible in the journey table but would be easy to lose behind larger rerun/review work. |
| Why it matters | These are cheap API consumer wins: they reduce source reading without changing runtime semantics. |
| Evidence | `FormFieldPublic` allows extra fields at `flow_models.py:657-665`; list-flow `count` is current-page count at `flow_authoring_router.py:172-176`; list-run `count` is current-page count at `flow_run_execution_router.py:80-85`; backend exposes `GET /flows/{id}/published/` at `flow_authoring_router.py:284-330`, but `flows.js` has no matching `flows.published` method in `flows.js:133-575`; create-run idempotency has no TTL/expiry predicate in `flow_run_repo.py:137-153`. |
| Current owner | HTTP schema/router owners in `flow_models.py`, `flow_authoring_router.py`, `flow_run_execution_router.py`; JS package owner in `flows.js`. |
| Proposed canonical home | Keep the backend schemas/routes as contract owners; make the JS package a generated-schema-backed ergonomic wrapper, not a separate contract. |
| Merge/delete path | Close or explicitly version `FormFieldPublic`; add `total_count`/`has_more` or document current-page `count`; add the published runtime client method; define idempotency-key retention. |
| Acceptance criteria | Consumer docs and generated/client methods can express happy-path pagination, published runtime discovery, run-contract fields, and idempotent retry retention without backend source reading. |
| Tests required | OpenAPI schema snapshot/contract test for `FormFieldPublic`; router pagination contract tests; `flows.test.js` method test for `flows.published`; idempotency replay test that captures the chosen retention rule. |
| Risk/trade-off | Closing `FormFieldPublic` may reject metadata currently tolerated by drafts; if flexibility is required, use a typed `metadata` field rather than arbitrary extras. |
| Human reviewability impact | Reviewers can approve small consumer-DX fixes independently before the high-blast-radius lifecycle slices. |
| Confidence | High. |

### Finding 3: Frontend runtime types are not single-source-of-truth

| Field | Detail |
|---|---|
| Problem | `intric-js` manually defines Flow run, step, evidence, and status types that overlap generated OpenAPI schemas. |
| Why it matters | Every status or schema change requires hand edits in multiple places, and subtle optionality drift is easy to miss. |
| Evidence | Manual `FlowRun` and status union at `resources.d.ts:295-311`; manual `FlowRunStepOutput` at `resources.d.ts:326-342`; manual `FlowStepResult` at `resources.d.ts:344-366`; generated `FlowRunStatus` at `schema.d.ts:12924-12927` and generated `FlowRunStepPublic` at `schema.d.ts:12961-13026`. |
| Current owner | `frontend/packages/intric-js/src/types/resources.d.ts` and generated `schema.d.ts` both claim ownership. |
| Proposed canonical home | `schema.d.ts` generated OpenAPI components; `resources.d.ts` should re-export aliases only. |
| Merge/delete path | Replace manual Flow runtime blocks with aliases like `components["schemas"]["FlowRunPublic"]`, `components["schemas"]["FlowRunStepPublic"]`, `components["schemas"]["FlowRunEvidenceResponse"]`, and `components["schemas"]["FlowRunStatus"]`. |
| Acceptance criteria | Adding a backend status changes generated schema and all frontend runtime types without a handwritten union edit. |
| Tests required | `pnpm -C frontend check` or package-scoped equivalent; `flows.test.js` route tests continue to pass; type import smoke tests for common Flow types. |
| Risk/trade-off | Existing app code may depend on friendlier aliases; preserve ergonomic exported names but map them to generated components. |
| Human reviewability impact | Public contract diffs become generated schema changes plus small alias diffs, not manual parallel edits. |
| Confidence | High. |

### Finding 4: Advanced lifecycle states require coordinated migration, not endpoint-only work

| Field | Detail |
|---|---|
| Problem | Runtime statuses are closed across enums, DB CHECK constraints, indexes, repository filters, generated types, and frontend hand types. |
| Why it matters | Adding `awaiting_review`, `paused`, or `rerunning` without a migration plan will break persistence or leave runs invisible to reconciliation/UI. |
| Evidence | Backend status enums at `enums.py:64-85`; run CHECK at `flow_tables.py:397-400`; step result CHECK at `flow_tables.py:503-506`; attempt CHECK at `flow_tables.py:570-572`; running partial index at `flow_tables.py:439-444`; stale-running query filters only `FlowRunStatus.RUNNING` at `flow_run_repo.py:225-241`; generated FlowRunStatus at `schema.d.ts:12924-12927`; manual frontend status at `resources.d.ts:301` and `resources.d.ts:331,358`. |
| Current owner | Split between backend enum, SQLAlchemy migration/table, repository queries, generated schema, and frontend manual types. |
| Proposed canonical home | Backend enum + DB migration for persisted states; generated OpenAPI types for frontend; explicit lifecycle transition table in `FlowRunService`/runtime docs. |
| Merge/delete path | Delete manual frontend status unions before adding states. Add one new state at a time with migration, index, reconciliation, audit, and contract tests. |
| Acceptance criteria | `awaiting_review` state is persisted, indexed, returned by API, rendered by frontend, excluded from stale-running failure, and audited. |
| Tests required | Migration tests for CHECK constraints; repository query tests; API contract tests; frontend status presentation tests; worker crash recovery tests. |
| Risk/trade-off | New statuses are breaking API changes; pre-production status makes that acceptable if done now with generated-client alignment. |
| Human reviewability impact | A state-machine change becomes one coherent diff with all affected surfaces visible. |
| Confidence | High. |

### Finding 5: Redispatch response shape should not become the rerun precedent

| Field | Detail |
|---|---|
| Problem | `FlowRunRedispatchResponse` returns `redispatched_count: int`, but the public endpoint can only redispatch at most one run. |
| Why it matters | A count-shaped response suggests public batch semantics and invites a future rerun API to copy the wrong abstraction. |
| Evidence | Response schema has `redispatched_count: int` at `flow_models.py:530-536`; endpoint calls `redispatch_stale_queued_runs(..., limit=1)` at `flow_run_execution_router.py:416-421`; frontend converts count > 0 into success at `FlowRunsTable.svelte:239-248` and `flowRunRedispatchFeedback.ts:1-5`. |
| Current owner | `flow_models.py` schema plus `flow_run_execution_router.py` endpoint. |
| Proposed canonical home | Keep redispatch as stale-queue recovery; reshape response to `redispatched: bool` and `reason: str | None`. |
| Merge/delete path | Pre-prod breaking change: update backend tests, generated schema, `resources.d.ts` alias, and frontend toast logic. |
| Acceptance criteria | Public response accurately represents one-run redispatch and cannot be mistaken for rerun/batch execution. |
| Tests required | Router tests for redispatched true/false; frontend toast unit test using boolean response. |
| Risk/trade-off | Breaking change to any existing local frontend/test caller; low risk before production. |
| Human reviewability impact | Future rerun design will not inherit misleading count semantics. |
| Confidence | High. |

### Finding 6: Evidence export contract conflicts with download semantics

| Field | Detail |
|---|---|
| Problem | Evidence export route declares `response_model=FlowRunEvidenceExportResponse` but returns a raw `Response` with `Content-Disposition` attachment. |
| Why it matters | Generated clients will expect JSON schema semantics while browser/client code may need file download handling. |
| Evidence | Route declares response model at `flow_run_evidence_router.py:138-143`; implementation returns `Response(..., headers={"Content-Disposition": ...})` at `flow_run_evidence_router.py:246-250`; generated operation says `application/json` returns `FlowRunEvidenceExportResponse` at `schema.d.ts:34028-34035`. |
| Current owner | `flow_run_evidence_router.py` and `flow_models.py`. |
| Proposed canonical home | Decide explicitly: either JSON API response (`FlowRunEvidenceExportResponse`) or file download endpoint with download-oriented OpenAPI metadata and client method. |
| Merge/delete path | If JSON API response, return the Pydantic response and let frontend download locally. If attachment, remove misleading response model and add generated-client support. |
| Acceptance criteria | Generated client type and runtime behavior agree; frontend evidence export does not rely on accidental fetch behavior. |
| Tests required | API contract test asserting content type/body/header; frontend package test for export method. |
| Risk/trade-off | Raw file download is convenient for browsers; JSON response is easier for SDK consumers. Pick one and document why. |
| Human reviewability impact | Reviewers can validate evidence export by contract, not by inspecting router implementation. |
| Confidence | High. |

## OpenAPI And Generated Client Usability

| Signal | Evidence | Verdict |
|---|---|---|
| Operation IDs exist for main endpoints | Create/list/get/cancel/redispatch/evidence/steps operation IDs appear in router definitions at `flow_run_execution_router.py:106-110`, `flow_run_execution_router.py:207-211`, `flow_run_execution_router.py:263-267`, `flow_run_execution_router.py:305-309`, `flow_run_execution_router.py:363-367`, `flow_run_evidence_router.py:66-70`, and `flow_run_steps_router.py:76-80`. | Good baseline. |
| Generated schema contains Flow operations | Generated paths include create run and follow-ups at `schema.d.ts:33622-34143`. | Good, but not fully consumed. |
| Handwritten JS client exists | `initFlows` wraps endpoints in `frontend/packages/intric-js/src/endpoints/flows.js:6-575`. | Useful ergonomics, but JSDoc uses `any` for core payloads (`flows.js:62-76`, `flows.js:414-422`). |
| Client has known type-check issue | `flows.js:433-441` normalizes `flow_id`, then deletes it; Phase 0 recorded the delete diagnostic. | Fix as part of generated-client alignment; split helper so create-run body never contains path-owned `flow_id`. |
| Frontend app consumes redispatch count | `FlowRunsTable.svelte:239-248` and `flowRunRedispatchFeedback.ts:1-5`. | Small blast radius for reshaping redispatch response. |

## Error And Idempotency Review

| Area | Current Behavior | Gap / Recommendation |
|---|---|---|
| Error shape | Endpoints use `error_response(...)` examples with `GeneralError`, e.g. create-run 400/403/404 at `flow_run_execution_router.py:113-140`. | Good baseline. Define a Problem Details-style or equivalent stable error model across all flow endpoints before public launch. |
| Validation errors | Generated operations still expose generic `HTTPValidationError`, e.g. create-run 422 at `schema.d.ts:33701-33708`. | Decide whether 422 is part of public contract or translated into the same machine-readable error envelope. |
| Create-run idempotency | Header documented at `flow_run_execution_router.py:45-49`; conflict handled at `flow_run_service.py:437-451`. | Good for create-run. Future rerun/resume endpoints need separate idempotency stories. |
| Idempotency retention | Repo lookup matches tenant/flow/key/principal and has no retention or expiry predicate at `flow_run_repo.py:137-153`. | Public contract should state whether keys are retained forever, retained for a fixed window, or pruned by Flow run retention. |
| Upload + create retry | JS helper can derive a stable upload-intent key at `flows.js:97-118`, then create uses the header at `flows.js:441-447`. | Useful but relies on Web Crypto (`flows.js:107-110`) and broad `any` payload normalization; document fallback for Node/server consumers. |
| Redispatch | Endpoint returns count and audits redispatch at `flow_run_execution_router.py:424-442`. | Treat as operational recovery, not user-facing retry/rerun. |

## Recommended Work Items

| Rank | Work Item | Scope | Acceptance Criteria | Tests | Risk / Trade-Off | Reviewability Impact | Confidence |
|---:|---|---|---|---|---|---|---|
| 1 | Make generated OpenAPI schemas the frontend Flow runtime type source. | `frontend/packages/intric-js/src/types/resources.d.ts`, `schema.d.ts`, app imports. | Manual `FlowRun`, `FlowRunStepOutput`, `FlowStepResult`, status unions replaced with generated aliases. | Typecheck plus import smoke tests. | May require small app typing fixes. | Removes parallel contract owner. | High |
| 2 | Add the missing `flows.published` JS client method. | `frontend/packages/intric-js/src/endpoints/flows.js`, generated schema aliases. | Package consumers can fetch `FlowRuntimePublic` without hand-constructing `/published/`. | `flows.test.js` route test. | Low risk; one wrapper around an existing endpoint. | Aligns the ergonomic client with the backend runtime discovery contract. | High |
| 3 | Fix or explicitly document pagination count semantics. | List flows/runs routers and client docs. | Responses expose `total_count`/`has_more`, or docs state that `count` means current-page count. | Router contract tests for `limit`/`offset`. | Adding total count may cost an extra DB count query. | Prevents every consumer from rediscovering pagination behavior. | High |
| 4 | Tighten public run-contract form field schema. | `FormFieldPublic`, run-contract OpenAPI, docs-site examples. | Arbitrary extras are removed, versioned, or moved under a typed `metadata` field. | OpenAPI schema contract test plus run-contract serialization test. | May require migrating metadata currently tolerated by drafts. | Makes generated form-rendering clients trust the contract. | High |
| 5 | Type or version `recommended_run_payload`. | `FlowInputPolicyPublic`, docs-site examples, generated schema. | The recommendation has a named schema or documented `JsonValue` escape hatch with owner. | Schema contract test. | Fully typing user-defined form values may be too strict; version platform-owned fields first. | Keeps input-policy guidance from becoming a second implicit request schema. | Medium |
| 6 | Extend `StepRunInput` instead of creating a new per-step file mapping schema. | `flow_models.py`, `normalize_step_file_associations`, generated types. | Step file mapping supports compact UUID lists and self-describing file associations. | API contract + runtime resolver tests. | Temporary dual-shape compatibility. | Keeps one canonical request owner. | High |
| 7 | Document and bound the top-level `file_ids` compatibility adapter. | `flow_run_service.py`, `step_input_resolution.py`, API docs/examples. | Adapter has owner, deletion condition/date, telemetry check, and tests; not silently removed. | Legacy top-level `file_ids` run test. | Keeps old shape briefly. | Future reviewers can delete it by checking named evidence, not re-litigating history. | High |
| 8 | Define create-run idempotency retention. | `flow_run_repo.py`, run retention policy, docs-site guide. | Public docs state key lifetime; repo query and cleanup behavior match that promise. | Idempotency replay/expiry tests. | Too-short retention can break slow retries; no retention can surprise long-lived clients. | Turns retry behavior into a contract instead of an implementation accident. | Medium |
| 9 | Reshape redispatch response before public launch. | `FlowRunRedispatchResponse`, router, generated client, frontend toast. | Response is `{run, redispatched, reason}` or equivalent, not count. | Router + frontend toast tests. | Breaking but low-risk pre-prod. | Keeps stale-queue recovery distinct from future rerun semantics. | High |
| 10 | Align evidence export OpenAPI with actual response behavior. | Evidence router/schema/client. | Contract says JSON response or download attachment, and implementation matches. | API contract + frontend export test. | Browser convenience vs SDK clarity. | Makes the generated client and router behavior reviewable together. | High |
| 11 | Design `awaiting_review` lifecycle as a standalone state-machine slice. | Enums, DB constraints, indexes, repos, generated types, frontend status. | One review state works end-to-end before edit/resume features land. | Migration/repo/API/frontend/runtime tests. | Medium migration blast radius. | Makes lifecycle diff coherent. | High |
| 12 | Design step rerun as a standalone endpoint and runtime slice. | API, service, runtime executor, attempts/results, audit. | Completed-run step rerun works with explicit downstream invalidation. | API + worker/runtime + idempotency tests. | Highest blast radius. | Keeps rerun separate from redispatch and review. | Medium |
| 13 | Keep the docs-site Flow guide tied to contract tests. | `frontend/apps/docs-site/src/content/guides/flows-api-guide.mdx`, OpenAPI examples. | Guide covers auth -> contract -> upload -> create -> poll -> steps -> evidence/artifacts plus explicit non-support for rerun/review until shipped. | Docs examples checked against generated OpenAPI examples. | Docs can rot unless examples are tested. | Reviewers can verify public docs against contract changes. | High |

## What Not To Do

| Do Not | Reason |
|---|---|
| Do not create `POST /runs/{id}/control/` with a string `action` field. | It hides authorization, idempotency, audit, and transition rules behind a primitive bag. |
| Do not delete top-level `file_ids` immediately. | Runtime still resolves it for step 1 at `step_input_resolution.py:401-402`, and persisted queued runs may depend on it. |
| Do not add frontend-only pause/review/rerun state. | Runtime statuses are persisted and closed in backend/DB (`enums.py:64-85`, `flow_tables.py:397-400`, `flow_tables.py:503-506`). |
| Do not mirror `redispatched_count` for rerun. | Redispatch count is already misleading for a one-run endpoint (`flow_run_execution_router.py:416-421`). |
| Do not create generic helpers or managers for runtime contracts. | The canonical owners already exist: HTTP schemas in `flow_models.py`, lifecycle behavior in `FlowRunService`, and generated TS schemas in `schema.d.ts`. |

## Contract Tests Required

| Test File Candidate | Test Type | Assertions |
|---|---|---|
| `backend/tests/integration/flows/test_flow_consumer_contract.py` | API contract | Published runtime view, run contract, input policy, upload, create run with idempotency, poll, steps, evidence, artifact signed URL. |
| `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py` | API + runtime | Multiple step-scoped uploads map to correct steps; legacy top-level `file_ids` still maps to step 1. |
| `backend/tests/integration/flows/test_flow_evidence_export_contract.py` | API contract | Evidence export OpenAPI-declared response matches implementation content type/header/body. |
| `frontend/packages/intric-js/src/endpoints/flows.test.js` | Client route tests | Published runtime method exists; create-run helper does not add/delete `flow_id`; redispatch response shape is boolean/reason. |
| `frontend/apps/web/src/lib/features/flows/components/flowRunStatusLabel.test.ts` | Frontend behavior | Status labels use generated statuses; future `awaiting_review` has explicit label/color. |
| Future `backend/tests/integration/flows/test_flow_review_pause_resume.py` | Runtime/API | Acceptance: review checkpoint pauses, edit persists with revision, resume rejects stale revision, audit events exist. Risk: requires enum/DB/reconciler migration first. Confidence: high on required behavior, medium on final endpoint shape. |
| Future `backend/tests/integration/flows/test_flow_step_rerun.py` | Runtime/API | Acceptance: rerun step with edited input appends attempt, idempotent retry returns same rerun operation, downstream invalidation policy is explicit. Risk: highest runtime blast radius. Confidence: medium until runtime/data-model reviews reconcile attempt semantics. |

## Risk Register

| Risk | Severity | Mitigation | Confidence |
|---|---:|---|---|
| Advanced workflow work becomes one giant PR touching API, DB, runtime, frontend, generated client, and audit. | High | Split into typed contract, state-machine, review/resume, and rerun slices. | High |
| Manual frontend types drift when adding new runtime states. | High | Delete/re-export generated Flow runtime types first. | High |
| Rerun idempotency accidentally returns the original parent run. | High | Define rerun-specific idempotency fingerprint including parent run, step, attempt, and edited input. | Medium |
| Evidence export generated client disagrees with runtime download behavior. | Medium | Align OpenAPI with implementation before public launch. | High |
| Compatibility adapter for top-level `file_ids` lives forever. | Medium | Document owner and deletion condition; write tests that make its scope explicit. | Medium |
| Adding `awaiting_review` misses stale-run reconciliation or indexing. | Medium | Include repo query/index/reconciler tests in lifecycle slice. | High |
| `FormFieldPublic` stays open-ended while generated clients assume a stable run form contract. | Medium | Close the schema or move extensibility into a typed/versioned `metadata` field. | High |
| Idempotency keys replay indefinitely because retention is not part of the public contract. | Medium | Define key retention in docs and align repo lookup/cleanup behavior. | Medium |

## Human Reviewability Impact

The API is close enough for basic usage that the highest-value work is not new endpoint volume. The reviewable path is to make existing contracts canonical first: generated types instead of handwritten runtime types, richer `StepRunInput` instead of a parallel file-mapping request, honest redispatch semantics, and response-shape alignment for evidence export. After that, review/edit/resume and step rerun can land as separate state-machine/runtime PRs with narrow acceptance criteria.

## Final Scorecard

Overall score: 4/10. The overall score is the minimum of the eight Agent E dimensions below; Single Source of Truth and Typed Contracts At Boundaries are the limiting scores.

| Dimension | Score | Justification |
|---|---:|---|
| Maintainability | 5 | Basic endpoints are cohesive, but contract ownership is split across backend schemas, JSONB payloads, generated types, handwritten frontend types, and runtime parsers. |
| Code Quality | 6 | Route descriptions and operation IDs are strong, but broad payload dictionaries and misleading `redispatched_count` reduce clarity. |
| Clean Architecture | 6 | Routers mostly act as adapters into services, but future advanced workflow features need explicit application/runtime ownership before more endpoint work. |
| Separation of Concerns | 5 | Runtime discovery, file mapping, lifecycle control, evidence, and client typing are separable concerns but not yet represented as separable implementation slices. |
| Single Source of Truth | 4 | Statuses and Flow runtime schemas have backend, DB, generated TS, and handwritten TS copies. |
| API Consumer DX | 5 | The happy path is usable; advanced workflows and SDK type alignment require source reading. |
| Runtime Reliability And Idempotency | 5 | Create-run idempotency and redispatch exist, but rerun/review states, pause crash behavior, review audit semantics, and idempotency retention are not public contracts. |
| Typed Contracts At Boundaries | 4 | `recommended_run_payload`, run input/output payloads, diagnostics, evidence snapshots, and frontend Flow runtime types still rely on broad JSON or manual duplication. |

## Claude Peer Review Notes

Claude iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and `MIN_SCORE: 5` for the initial direction. Accepted corrections:

- Reframed per-step file mapping from "missing typed file association object" to "existing `StepRunInput` is underspecified" because `StepRunInput` exists at `flow_models.py:410-411`.
- Split pause/review/edit/resume/rerun into separate slices instead of a bundled run-control recommendation.
- Treated top-level `file_ids` as a deliberate compatibility adapter until persisted/external usage is checked, based on `flow_run_service.py:385-390` and `step_input_resolution.py:401-402`.
- Elevated generated-client alignment as the first concrete deliverable, based on manual Flow runtime types in `resources.d.ts:295-366` and generated schemas in `schema.d.ts:11844-11890`, `schema.d.ts:12924-13054`.
- Added the redispatch response-shape finding after verifying frontend and test usage with `redispatched_count`.

Claude iteration 2 returned `GREEN_LIGHT: no` for document-structure issues, not source-evidence errors. Accepted corrections:

- Corrected the final score to 4/10 because the overall score is the minimum dimension score.
- Reduced the scorecard to eight Agent E dimensions and moved API maintainer/test/readability scoring back to the owning Phase 1 reviewers.
- Promoted `FormFieldPublic` openness, pagination `count`, missing `flows.published`, `recommended_run_payload`, and idempotency-retention gaps into findings and ranked work items.
- Added concrete top-level `file_ids` deletion criteria and named `normalize_step_file_associations` as the proposed runtime normalizer.
- Added acceptance, risk, and confidence detail to deferred review/resume and step-rerun tests.

Claude iteration 3 returned `VERDICT: green`, `GREEN_LIGHT: yes`, and `MIN_SCORE: 4` after those corrections.

Confidence: high for the findings grounded in cited files; medium for exact future endpoint shapes until Phase 1 runtime/data/API-maintainer reviews are reconciled.
