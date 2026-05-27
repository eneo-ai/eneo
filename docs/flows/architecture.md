# Flow Architecture

Scope: Flows proper. Flow AI Builder appears here only when a Flow proper file
depends on the same runtime or contract surface.

This document is the maintainer entry point for Flows. It names the current
owners, runtime journeys, blocked policy decisions, and guard tests.

## Mental Model

| Concept | Source of truth | Meaning |
| --- | --- | --- |
| Draft Flow | `flows` and `flow_steps` | Mutable authoring state. `flows.published_version` points at the active published snapshot when the flow is published, and draft updates increment `flows.draft_revision`. See `backend/src/intric/database/tables/flow_tables.py:141` and `backend/src/intric/flows/infrastructure/flow_repo.py:539`. |
| Published Flow Version | `flow_versions.definition_json` | Immutable runtime snapshot. It stores ordered step definitions, assistant execution snapshots, review policy, input/output policy, and the checksum used by runtime validation. See `backend/src/intric/database/tables/flow_tables.py:333` and `backend/src/intric/flows/application/flow_service.py:786`. |
| Run | `flow_runs` plus step/runtime child tables | One execution of a published version. The run stores principal identity, input payload, lifecycle status, revision, and output/error payloads. Step results and attempts use published snapshot step identity, not mutable draft identity. See `backend/src/intric/database/tables/flow_tables.py:568`, `backend/src/intric/database/tables/flow_tables.py:699`, and `backend/src/intric/database/tables/flow_tables.py:890`. |

Use this split when changing code:

1. Draft authoring changes start in `FlowService`, `FlowEditor`, or the authoring
   router.
2. Runtime contract changes start in `FlowRunContractService` and published
   definition parsing.
3. Execution changes start in `FlowRunService`, `FlowRunExecutor`, or the
   specific StepHandler or OutputFormatSpec.
4. Evidence, artifacts, review, rerun, and webhook delivery each have separate
   owners listed below.

## Canonical Owner Map

| Concept | Canonical owner | Main source evidence | Notes |
| --- | --- | --- | --- |
| Draft flow lifecycle | `FlowService` | `backend/src/intric/flows/application/flow_service.py:70` | Creates, updates, validates, publishes, and unpublishes flows. It should not leak FastAPI or frontend concepts. |
| Draft flow persistence | `FlowRepository` and `flow_tables.py` | `backend/src/intric/flows/infrastructure/flow_repo.py:529`, `backend/src/intric/database/tables/flow_tables.py:141` | `FlowRepository.update` owns optimistic draft revision writes. |
| Published snapshot shape | `published_definition.py` | `backend/src/intric/flows/published_definition.py:46`, `backend/src/intric/flows/published_definition.py:112`, `backend/src/intric/flows/published_definition.py:131`, `backend/src/intric/flows/published_definition.py:191` | Build and parse published definitions here. Do not read mutable draft steps during runtime. |
| Runtime consumer contract | `FlowRunContractService` | `backend/src/intric/flows/flow_run_contract_service.py:60`, `backend/src/intric/flows/flow_run_contract_service.py:66` | The run contract owns final output, form fields, runtime step inputs, upload limits, review requirements, and template readiness. |
| Runtime-safe Flow projection | `FlowAssembler.to_runtime_public` | `backend/src/intric/flows/api/flow_assembler.py:77` | Adds paths for run contract, uploads, run creation, review, evidence, and artifacts. |
| Flow API permission checks | `flow_access_policy.py` and `flow_api_common.py` | `backend/src/intric/flows/flow_access_policy.py:17`, `backend/src/intric/flows/api/flow_api_common.py:128` | Action policy decides who may call an endpoint. API helpers translate scope errors into `GeneralError` responses. |
| Run creation and dispatch | `FlowRunService` | `backend/src/intric/flows/application/flow_run_service.py:107`, `backend/src/intric/flows/application/flow_run_service.py:173` | Loads the published definition, validates input, enforces idempotency and concurrency, persists run and preseeded steps. |
| Worker entry point | `runtime/tasks.py` | `backend/src/intric/flows/runtime/tasks.py:81` | Resolves user or service-key principal and constructs the executor in the task process. |
| Runtime execution loop | `FlowRunExecutor` | `backend/src/intric/flows/runtime/executor.py:534` | Parses published runtime steps, claims step results, creates attempts, invokes StepHandlers, opens review, inserts webhook delivery intents, and finalizes runs. |
| Output-mode behavior | `runtime/step_handlers` | `backend/src/intric/flows/runtime/step_handlers/__init__.py:21`, `backend/src/intric/flows/runtime/executor.py:1007` | `output_mode` chooses behavior: pass-through, HTTP post, transcription-only, or template-fill. Add modes by adding one handler entry and updating the executor construction guard. |
| Output-type policy | `runtime/output_formats` | `backend/src/intric/flows/runtime/output_formats/__init__.py:19`, `backend/src/intric/flows/runtime/output_formats/base.py:84` | `output_type` owns prompt instructions, native JSON-mode preference, validation/rendering requirements, and renderer selection. |
| Byte rendering | `runtime/document_rendering` and renderer deps | `backend/src/intric/flows/runtime/output_formats/base.py:34`, `backend/src/intric/flows/runtime/output_runtime.py:59` | Renderer functions are leaf adapters. Keep DOCX/PDF/Markdown libraries out of executor and step handlers. |
| Runtime output artifacts | `output_runtime.py` | `backend/src/intric/flows/runtime/output_runtime.py:71`, `backend/src/intric/flows/runtime/output_runtime.py:112` | Persists rendered artifact bytes through the runtime principal owner fields. |
| Webhook delivery outbox | `FlowRunWebhookDeliveryRepository` and `FlowRunWebhookDeliveryService` | `backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py:38`, `backend/src/intric/flows/runtime/flow_webhook_delivery.py:88` | Executor only inserts delivery intents. The outbox worker claims, delivers, retries, dead-letters, and finalizes. |
| Runtime lifecycle audit outbox | `FlowRunAuditOutboxDeliveryService` | `backend/src/intric/flows/application/flow_run_audit_outbox_delivery.py:43` | Lifecycle audit is committed runtime state and is delivered outside tenant audit feature flags. |
| Evidence and artifacts | `FlowRunEvidenceService`, `flow_run_evidence.py`, `flow_run_export_json.py` | `backend/src/intric/flows/application/flow_run_evidence_service.py:33`, `backend/src/intric/flows/flow_run_evidence.py:74`, `backend/src/intric/flows/flow_run_export_json.py:218` | Evidence assembly, export, redaction, artifact availability, and retention summaries belong here. |
| Retention tombstones | `flow_retention_tombstone.py` | `backend/src/intric/flows/flow_retention_tombstone.py:8`, `backend/src/intric/flows/flow_retention_tombstone.py:50` | The tombstone schema exists, but product/data decisions still block the full retention policy work. |
| Review checkpoints | `FlowRunReviewCheckpointService` | `backend/src/intric/flows/application/flow_run_review_checkpoint_service.py:28` | Owns active checkpoint lookup, payload edit validation, approve/reject, resume, revision checks, and deadline behavior. |
| Step rerun | `FlowRunRerunService` | `backend/src/intric/flows/application/flow_run_rerun_service.py:52`, `backend/src/intric/database/tables/flow_tables.py:777` | Rerun remains user-principal-only in persistence and API policy. |
| Frontend draft editing | `FlowEditor.ts` | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:77`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:479` | Owns editable fields, step order mutations, active step selection, and metadata writes. |
| Frontend draft form schema | `flowFormSchema.ts`, `FlowEditor.ts`, `FlowFormSchemaEditor.svelte` | `frontend/apps/web/src/lib/features/flows/flowFormSchema.ts:73`, `frontend/apps/web/src/lib/features/flows/flowFormSchema.ts:114`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:517` | `flowFormSchema.ts` owns field normalization and metadata shape. `FlowEditor` writes metadata. The editor component owns transient local editing state. |
| Frontend run contract payload | `flowRunContract.ts` | `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:51`, `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:171` | Builds step file payloads, required field checks, reused input, and create-run intent from generated contract types. |
| Frontend run wizard | `flowRunWizard.ts` | `frontend/apps/web/src/lib/features/flows/flowRunWizard.ts:78`, `frontend/apps/web/src/lib/features/flows/flowRunWizard.ts:145` | Derives wizard pages and blockers from the backend run contract and file state. |
| Frontend runtime files | `FlowRunFileInputState.svelte.ts` and `FlowRunDialog.svelte` | `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.svelte.ts:19`, `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:507` | State lives in `FlowRunFileInputState`; browser upload side effects still live in the dialog. Moving that boundary needs a design gate. |
| Frontend recording lifecycle | `RecordingSession` and `flowRunRecordingSession.ts` | `frontend/apps/web/src/lib/features/audio/recordingSession.ts:1`, `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.ts:1` | `RecordingSession` owns recorder lifecycle and retry. `flowRunRecordingSession` owns segment filenames, IndexedDB persistence, and resume recovery helpers. |

## Runtime Consumer Journey

Use this journey for public API, SDK, and frontend changes:

1. Discover the published flow through `GET /api/v1/flows/{id}/published/`.
   The response is a runtime-safe projection, including runtime path templates
   from `FlowAssembler.to_runtime_public`. See
   `backend/src/intric/flows/api/flow_authoring_router.py:445` and
   `backend/src/intric/flows/api/flow_assembler.py:85`.
   This consumer projection currently lives in the authoring router file, so do
   not assume runtime-consumer routes all live under `flow_run_execution_router.py`.
2. Load `GET /api/v1/flows/{id}/run-contract/`. This is the canonical runtime
   input contract. The endpoint describes form fields, runtime input steps,
   upload limits, review steps, final output, and template readiness. See
   `backend/src/intric/flows/api/flow_upload_router.py:44` and
   `backend/src/intric/flows/flow_run_contract_service.py:66`.
3. Upload files through the flow or step runtime-file endpoints. Service-key
   callers may use published runtime uploads only. See
   `backend/src/intric/flows/api/flow_upload_router.py:128` and
   `backend/src/intric/flows/api/flow_upload_router.py:231`.
4. Create the run with `expected_flow_version` from the run contract. `FlowRunService`
   rejects stale versions before it persists the run. See
   `backend/src/intric/flows/application/flow_run_service.py:173` and
   `backend/src/intric/flows/application/flow_run_service.py:227`.
5. Poll run status and step output. The router documents polling and terminal
   status capability semantics. See
   `backend/src/intric/flows/api/flow_run_execution_router.py:89` and
   `backend/src/intric/flows/api/flow_run_execution_router.py:414`.
6. If a run pauses at `awaiting_review`, use the active checkpoint endpoint, then
   edit, approve, reject, or resume through the checkpoint paths. See
   `backend/src/intric/flows/api/flow_run_execution_router.py:198`,
   `backend/src/intric/flows/api/flow_run_execution_router.py:704`,
   `backend/src/intric/flows/api/flow_run_execution_router.py:800`, and
   `backend/src/intric/flows/api/flow_run_execution_router.py:947`.
7. Download artifacts or evidence through the run artifact/evidence endpoints.
   Artifact content may return gone after retention purges file content. See
   `backend/src/intric/flows/api/flow_run_evidence_router.py:67` and
   `backend/src/intric/flows/application/flow_run_evidence_service.py:80`.

## Authoring And Publish Journey

The authoring path edits draft state and then freezes a runtime snapshot:

1. The authoring router stays thin: parse request, resolve auth/scope, call
   `FlowService`, assemble a public response.
2. `FlowService.create_flow` and `FlowService.update_flow` normalize metadata,
   validate steps, validate assistant scope, validate security classification,
   and persist through `FlowRepository`. See
   `backend/src/intric/flows/application/flow_service.py:100` and
   `backend/src/intric/flows/application/flow_service.py:197`.
3. `FlowRepository.update` owns the SQL update and draft revision increment. See
   `backend/src/intric/flows/infrastructure/flow_repo.py:539`.
4. `FlowService.publish_flow` validates publishability, chooses the next version,
   builds `definition_json`, writes `flow_versions`, and updates
   `flows.published_version`. See
   `backend/src/intric/flows/application/flow_service.py:391`.
5. Published `definition_json` stores ordered runtime steps and assistant snapshots.
   Do not make runtime code reach back to mutable `flow_steps`. See
   `backend/src/intric/flows/application/flow_service.py:786` and
   `backend/src/intric/flows/published_definition.py:191`.

## Runtime Execution Journey

The run lifecycle is database-first:

1. The API calls `FlowRunService.create_run`, which loads the published flow,
   validates the submitted payload, precomputes runtime step input file
   projections, and persists the run with a typed principal identity. See
   `backend/src/intric/flows/application/flow_run_service.py:213`,
   `backend/src/intric/flows/application/flow_run_service.py:255`, and
   `backend/src/intric/flows/application/flow_run_service.py:374`.
2. The router commits before dispatching the worker task, so Celery starts from
   committed run state. See
   `backend/src/intric/flows/api/flow_run_execution_router.py:458`.
3. The Celery task resolves the principal from `flow_runs.principal_type`,
   `principal_user_id`, or `principal_api_key_id`, then constructs the executor.
   See `backend/src/intric/flows/runtime/tasks.py:81`.
4. The executor parses the published runtime steps, validates assistant snapshots,
   and rebuilds execution state from persisted step results. See
   `backend/src/intric/flows/runtime/executor.py:534` and
   `backend/src/intric/flows/runtime/executor.py:553`.
5. For each step, the executor checks cancellation/deletion, claims a step result,
   starts an attempt, invokes the resolved StepHandler, persists success or
   failure, and updates the in-memory execution state from persisted results. See
   `backend/src/intric/flows/runtime/executor.py:596`,
   `backend/src/intric/flows/runtime/executor.py:640`,
   `backend/src/intric/flows/runtime/executor.py:697`,
   `backend/src/intric/flows/runtime/executor.py:727`, and
   `backend/src/intric/flows/runtime/executor.py:822`.
6. Review policy pauses the run after the completed step result is persisted.
   HTTP post steps insert webhook delivery intents and return with the run still
   running. See `backend/src/intric/flows/runtime/executor.py:858` and
   `backend/src/intric/flows/runtime/executor.py:868`.
7. When all steps complete, `finalize_run_from_current_results` terminalizes the
   run from persisted result state. See
   `backend/src/intric/flows/runtime/executor.py:881`.

## Step Behavior And Output Format

Flows separate the two axes that used to drift together:

| Axis | Owner | What it owns | What it must not own |
| --- | --- | --- | --- |
| `output_mode` | StepHandler registry and handler classes | Runtime behavior: call the LLM, skip the LLM for transcription, run template fill, or queue a webhook delivery intent. See `backend/src/intric/flows/runtime/step_handlers/__init__.py:21`. | Prompt instructions, JSON-mode policy, document rendering, or output-type validation. |
| `output_type` | OutputFormatSpec registry and specs | Prompt instructions, native JSON object-mode preference, output validation, document rendering requirement, and renderer choice. See `backend/src/intric/flows/runtime/output_formats/base.py:84`. | Step behavior dispatch, run lifecycle, webhook delivery, or review checkpoint lifecycle. |
| OutputRenderer role | `runtime/document_rendering` leaves passed through `OutputRuntimeDeps` | Byte rendering for DOCX/PDF/Markdown-derived artifacts. See `backend/src/intric/flows/runtime/output_formats/base.py:34` and `backend/src/intric/flows/runtime/output_runtime.py:59`. | Business policy, persistence ownership, or a plugin SDK. |

`FlowRunExecutor._execute_step` resolves the StepHandler from `output_mode`.
`step_execution_runtime.py` prepares the assistant call and calls
`process_typed_output`. `output_runtime.py` resolves the OutputFormatSpec from
`output_type` and persists rendered artifacts. See
`backend/src/intric/flows/runtime/executor.py:1007`,
`backend/src/intric/flows/runtime/step_execution_runtime.py:175`, and
`backend/src/intric/flows/runtime/output_runtime.py:71`.

## Webhook Outbox Lifecycle

HTTP post is durable outbox work:

1. `HttpPostStepHandler` wraps pass-through execution and emits one
   `WebhookDeliveryIntent` with a run, step, attempt, and idempotency key. See
   `backend/src/intric/flows/runtime/step_handlers/http_post.py:16` and
   `backend/src/intric/flows/runtime/step_handlers/http_post.py:39`.
2. The executor inserts pending delivery rows after the step result is persisted
   and commits before returning `running`. See
   `backend/src/intric/flows/runtime/executor.py:868`.
3. The webhook repository uses `ON CONFLICT DO NOTHING` for idempotent insert and
   `FOR UPDATE SKIP LOCKED` for delivery claims. See
   `backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py:38`
   and `backend/src/intric/flows/infrastructure/flow_run_webhook_delivery_repo.py:76`.
4. `FlowRunWebhookDeliveryService.deliver_due` claims one row at a time, commits
   the claim, prepares the payload from the published snapshot and current step
   result, sends HTTP, records success or retry/dead-letter failure, and finalizes
   the run after success. See
   `backend/src/intric/flows/runtime/flow_webhook_delivery.py:117`,
   `backend/src/intric/flows/runtime/flow_webhook_delivery.py:202`,
   `backend/src/intric/flows/runtime/flow_webhook_delivery.py:267`,
   `backend/src/intric/flows/runtime/flow_webhook_delivery.py:317`, and
   `backend/src/intric/flows/runtime/flow_webhook_delivery.py:360`.
5. The data model enforces one delivery per `(flow_run_id, step_id, attempt_no)`
   and uses the shared outbox delivery status vocabulary. See
   `backend/src/intric/database/tables/flow_tables.py:1609` and
   `backend/src/intric/database/tables/flow_tables.py:1664`.

## Runtime Step Identity

Runtime step identity is snapshot-owned:

1. Published definitions contain step ids and ordered runtime steps. Runtime code
   parses these through `parse_published_runtime_steps`. See
   `backend/src/intric/flows/published_definition.py:191`.
2. Run creation pre-seeds step results from published step identities. See
   `backend/src/intric/flows/application/flow_run_service.py:277`.
3. `flow_step_results.step_id` and `flow_step_attempts.step_id` are non-null,
   with uniqueness per run/step and per run/step/attempt. See
   `backend/src/intric/database/tables/flow_tables.py:715`,
   `backend/src/intric/database/tables/flow_tables.py:768`,
   `backend/src/intric/database/tables/flow_tables.py:906`, and
   `backend/src/intric/database/tables/flow_tables.py:976`.
4. Rerun, review, evidence, webhook, result-file, and audit rows all refer to the
   runtime snapshot step, not to a mutable draft step lookup at execution time.

Do not reintroduce fallback by `step_order` as runtime truth unless a new board
task proves an unavoidable current caller need. There are no production Flow
users, so legacy compatibility is not a reason by itself.

## Files, Artifacts, Evidence, And Retention

Runtime file ownership is principal-aware:

1. Run creation stores a typed principal identity on `flow_runs`. The database
   check requires either a user principal or a service-key principal, not both.
   See `backend/src/intric/database/tables/flow_tables.py:575` and
   `backend/src/intric/database/tables/flow_tables.py:635`.
2. Rendered output artifacts are stored by `output_runtime.py` with
   `deps.principal.file_owner_fields()` and the run tenant. See
   `backend/src/intric/flows/runtime/output_runtime.py:112`.
3. `FlowRunEvidenceService` owns artifact file access, redacted evidence bundles,
   and evidence JSON export. It returns `flow_run_artifact_content_unavailable`
   when retention has purged artifact content. See
   `backend/src/intric/flows/application/flow_run_evidence_service.py:33` and
   `backend/src/intric/flows/application/flow_run_evidence_service.py:60`.
4. `flow_run_evidence.py` builds the debug export from the published definition,
   run, step results, attempts, result files, rerun operations, and invalidated
   steps. See `backend/src/intric/flows/flow_run_evidence.py:74`.
5. `flow_run_export_json.py` summarizes retention state and artifact availability
   for evidence exports. See
   `backend/src/intric/flows/flow_run_export_json.py:218` and
   `backend/src/intric/flows/flow_run_export_json.py:279`.
6. `flow_retention_tombstone.py` defines the tombstone payloads used when run
   evidence or generated artifacts are purged. See
   `backend/src/intric/flows/flow_retention_tombstone.py:50`.

Retention remains an open product/data decision. The code has tombstone and export
support, but the board still blocks full retention policy and service-key identity
decisions. Do not fill those gaps with compatibility code.

## Review, Rerun, And Service-Key Decisions

Review and rerun are separate runtime features:

1. `FlowRunReviewCheckpointService` owns active checkpoint lookup, payload edit,
   approval, rejection, resume, revision checks, and expiry behavior. See
   `backend/src/intric/flows/application/flow_run_review_checkpoint_service.py:28`.
2. Review checkpoint API docs tell clients to render from immutable checkpoint
   step snapshots rather than mutable draft definitions. See
   `backend/src/intric/flows/api/flow_run_execution_router.py:198`.
3. `FlowRunRerunService` owns step rerun acceptance, invalidation graph logic,
   input validation, request fingerprinting, and idempotent replay. See
   `backend/src/intric/flows/application/flow_run_rerun_service.py:52` and
   `backend/src/intric/flows/application/flow_run_rerun_service.py:86`.
4. Rerun persistence currently requires a human actor. The table check enforces
   `requested_by_principal_type = 'user'`. See
   `backend/src/intric/database/tables/flow_tables.py:823` and
   `backend/src/intric/database/tables/flow_tables.py:843`.
5. API policy allows service-key principals for published runtime view/run and
   for own-run review/resume when requested, but not for rerun. See
   `backend/src/intric/flows/flow_access_policy.py:82`,
   `backend/src/intric/flows/flow_access_policy.py:179`, and
   `backend/src/intric/flows/flow_access_policy.py:191`.

Current service-key posture: service keys can use the published runtime surface
and own-run review/resume paths. Rerun and broader service-key identity semantics
remain blocked by product/data decisions. Because there are no production Flow
users, the next approved task should prefer the cleaner long-term model over a
legacy-preserving compromise.

## API And Frontend Contract Ownership

Backend contract owners:

| Contract surface | Backend owner | Frontend/SDK owner |
| --- | --- | --- |
| Published runtime projection | `FlowAssembler.to_runtime_public` and `flow_authoring_router.py` | `frontend/packages/intric-js/src/endpoints/flows.js` published/runtime helpers |
| Run contract | `FlowRunContractService` and `flow_upload_router.py` | `frontend/apps/web/src/lib/features/flows/flowRunContract.ts` |
| Runtime file uploads | `flow_upload_router.py` and file upload service | `FlowRunDialog.svelte` side effects plus `FlowRunFileInputState.svelte.ts` state |
| Run lifecycle and polling | `flow_run_execution_router.py`, `FlowRunService`, `FlowRunExecutor` | Flow run progress/history components and generated SDK types |
| Review checkpoints | `FlowRunReviewCheckpointService` and review checkpoint routes | `FlowRunReviewCheckpointPanel.svelte` and `flowRuntimeErrorMapping.ts` |
| Evidence/artifact export | `FlowRunEvidenceService` and evidence router | `FlowRunEvidence.svelte`, evidence actions, and SDK evidence/artifact helpers |

API rules:

1. Public errors go through `GeneralError` response metadata and Flow API error
   helpers. See `backend/src/intric/flows/api/flow_api_common.py:49` and
   `backend/src/intric/flows/api/flow_api_common.py:90`.
2. Scope and published-flow requirements belong in `enforce_flow_scope`,
   `resolve_flow_access_context`, and `flow_access_policy.py`. See
   `backend/src/intric/flows/api/flow_api_common.py:128` and
   `backend/src/intric/flows/api/flow_api_common.py:191`.
3. Frontend runtime input payload construction belongs in `flowRunContract.ts`,
   not in Svelte components. Components should consume the generated contract
   and call these helpers. See
   `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:51`.
4. Frontend draft step order and metadata writes belong in `FlowEditor.ts`, not
   in step-list components. See
   `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:479` and
   `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:510`.

## Architecture Guard Tests

Run these when changing the named surface:

| Surface | Guard or test |
| --- | --- |
| No FastAPI exceptions from Flow application/runtime modules | `backend/tests/unittests/flows/test_flow_architecture_guards.py:476` |
| `output_mode` dispatch remains in StepHandlers | `backend/tests/unittests/flows/test_flow_architecture_guards.py:497` and `backend/tests/unittests/flows/test_flow_runtime_step_handlers.py:161` |
| `output_type` policy remains in OutputFormatSpecs | `backend/tests/unittests/flows/test_flow_architecture_guards.py:507` and `backend/tests/unittests/flows/test_flow_runtime_output_formats.py:25` |
| Removed typed-output helpers do not come back | `backend/tests/unittests/flows/test_flow_architecture_guards.py:554` |
| Webhook delivery stays out of the executor | `backend/tests/unittests/flows/test_flow_architecture_guards.py:571` |
| Shared outbox delivery status vocabulary | `backend/tests/unittests/flows/test_flow_architecture_guards.py:596` and `backend/tests/unittests/flows/test_flow_architecture_guards.py:666` |
| Document rendering dependencies stay in leaves | `backend/tests/unittests/flows/test_flow_runtime_output_renderers.py:120` |
| Runtime output format prompt/JSON-mode behavior | `backend/tests/unittests/flows/test_flow_runtime_output_formats.py:59` and `backend/tests/unittests/flows/test_flow_runtime_output_formats.py:180` |
| Published definition contract | `backend/tests/unittests/flows/test_published_definition_contract.py` |
| Run contract service | `backend/tests/unittests/flows/test_flow_run_contract_service.py` |
| Consumer API contract | `backend/tests/integration/flows/test_flow_consumer_api_contract.py` |
| Worker runtime contract | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py` |
| Webhook outbox delivery | `backend/tests/integration/flows/test_flow_webhook_outbox_delivery.py` |
| Evidence API contracts | `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` |
| Frontend run contract payload helpers | `frontend/apps/web/src/lib/features/flows/flowRunContract.test.ts` |
| Frontend run wizard and blockers | `frontend/apps/web/src/lib/features/flows/flowRunWizard.test.ts` |
| Frontend file input state | `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.test.ts` |
| Frontend recording persistence/recovery | `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.test.ts` and `frontend/apps/web/src/lib/features/audio/recordingSession.test.ts` |
| Frontend draft editor ownership | `frontend/apps/web/src/lib/features/flows/FlowEditor.test.ts` |

## Where To Change X

| Change | Start here | Guard to run |
| --- | --- | --- |
| Add or rename a persisted Flow draft field | `FlowService`, `flow_models.py`, `flow_tables.py`, `backend/alembic/versions`, `FlowEditor.ts` | Alembic migration review, Flow service/router tests, `FlowEditor.test.ts`, generated client update if OpenAPI changes |
| Add a field to the published runtime snapshot | `published_definition.py`, `FlowService._step_to_definition` | `test_published_definition_contract.py`, worker/runtime tests |
| Change run contract shape | `FlowRunContractService` and `flow_upload_router.py` | `test_flow_run_contract_service.py`, `test_flow_consumer_api_contract.py`, generated SDK/frontend tests |
| Change runtime upload rules | `flow_upload_router.py`, upload service, `FlowRunFileInputState`, `FlowRunDialog` | upload router tests, `flowRunContract.test.ts`, `FlowRunFileInputState.test.ts`, `flowRunWizard.test.ts` |
| Add an output mode | `runtime/step_handlers` | StepHandler registry tests and output-mode branch guard |
| Add an output type | `runtime/output_formats` | OutputFormatSpec registry tests, output-type branch guard, document renderer guard if it renders bytes |
| Change DOCX/PDF rendering | `runtime/document_rendering` or `docx_template_runtime.py` | output renderer tests, output runtime tests, template fill runtime tests |
| Change webhook delivery semantics | `HttpPostStepHandler`, webhook outbox repo/service | webhook outbox delivery tests and executor no-inline-delivery guard |
| Change run terminalization | `FlowRunTerminalizer`, executor, webhook delivery finalization | terminalization, worker contract, audit outbox tests |
| Change review checkpoint behavior | `FlowRunReviewCheckpointService` and review routes | review checkpoint service/router tests and frontend review panel tests |
| Change rerun behavior | `FlowRunRerunService` and rerun routes | rerun service/repository/API tests |
| Change service-key Flow permissions | `flow_access_policy.py`, `flow_api_common.py`, affected routers | service-key permission tests, API contract/OpenAPI tests |
| Change evidence export | `FlowRunEvidenceService`, `flow_run_evidence.py`, `flow_run_export_json.py` | evidence service/API/export tests |
| Change retention/tombstone semantics | `flow_retention_tombstone.py`, retention policy/worker files | retention tests plus product/data decision receipt |
| Change frontend draft step order | `FlowEditor.ts` | `FlowEditor.test.ts` |
| Change frontend run launch payload | `flowRunContract.ts` | `flowRunContract.test.ts`, `flowRunWizard.test.ts`, relevant component tests |
| Change recording retry/lifecycle | `RecordingSession` | `recordingSession.test.ts` |
| Change recording persistence or resume | `flowRunRecordingSession.ts`, `FlowRunFileInputState`, `FlowRunDialog` | `flowRunRecordingSession.test.ts`, `FlowRunFileInputState.test.ts`, run dialog focused tests |

## Known Open Decisions And Compatibility Paths

| Item | Current owner | Status | Deletion or decision trigger |
| --- | --- | --- | --- |
| Runtime retention policy | Retention policy files, tombstone schema, evidence export | Blocked by product/data decisions in the goal board. | Owner decides retention windows, purge behavior, and export guarantees. Then implement through a dedicated Worker with data/schema preflight. |
| Service-key identity for review/rerun | `flow_access_policy.py`, `FlowRunReviewCheckpointService`, `FlowRunRerunService`, rerun table constraints | Review/resume supports service-key own-run paths. Rerun is still human-user-only. | Product decides whether machine clients may rerun and how audit attribution should work. With no production Flow users, prefer a clean typed model over compatibility. |
| Form-schema dirty local edit conflict behavior | `flowFormSchema`, `FlowEditor`, `FlowFormSchemaEditor` | Blocked by product/UX decision. | Decide whether local dirty edits merge, overwrite, warn, or discard when persisted metadata changes. Then deepen or delete the local buffering path. |
| Browser upload/audio side-effect ownership | `FlowRunDialog`, `FlowRunFileInputState`, `flowRunRecordingSession`, `RecordingSession` | Current split is source-backed: `RecordingSession` is lifecycle/retry only, while persistence/upload remains in the dialog and recording ledger helpers. Moving side effects needs a design gate. | Approve a single browser-side owner with behavior tests, then move behavior rather than copying it. |
| Evidence export raw/detail policy | Evidence router and `FlowRunEvidenceService` | Raw export requires an explicit reason and separate access kind. See `backend/src/intric/flows/api/flow_run_evidence_router.py:141` and `backend/src/intric/flows/application/flow_run_evidence_service.py:131`. | Product/security decides whether raw export remains, narrows, or is removed before public launch. |

Compatibility paths are not architecture goals. Keep one only when a current
caller, current data, or recorded product decision requires it. Otherwise, create
a Scout/Judge/Worker pair that proves zero need and deletes the weaker path.
