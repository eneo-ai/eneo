# Flow Architecture

Scope: Flows proper. Flow AI Builder appears here only when a Flow proper file
depends on the same runtime or contract surface.

This document is the maintainer entry point for Flows. It names the current
owners, runtime journeys, blocked policy decisions, and guard tests.
Use [Flow Package Layout](./package-layout.md) before adding or moving
top-level Flow modules.

Related docs:

- [Flow Developer Quickstart](./flow-developer-quickstart.md)
- [Flow Package Layout](./package-layout.md)

## Mental Model

| Concept                | Source of truth                            | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Draft Flow             | `flows` and `flow_steps`                   | Mutable authoring state. `flows.published_version` points at the active published snapshot when the flow is published, and draft updates increment `flows.draft_revision`. See `backend/src/eneo/database/tables/flow_tables.py::Flows` and `backend/src/eneo/flows/infrastructure/flow_repo.py::FlowRepository.update`.                                                                                                                      |
| Published Flow Version | `flow_versions.definition_json`            | Immutable runtime snapshot. It stores ordered step definitions, assistant execution snapshots, review policy, input/output policy, and the checksum used by runtime validation. See `backend/src/eneo/database/tables/flow_tables.py::FlowVersions` and `backend/src/eneo/flows/application/flow_service.py::FlowService._build_definition`.                                                                                                                 |
| Run                    | `flow_runs` plus step/runtime child tables | One execution of a published version. The run stores principal identity, input payload, lifecycle status, revision, and output/error payloads. Step results and attempts use published snapshot step identity, not mutable draft identity. See `backend/src/eneo/database/tables/flow_tables.py::FlowRuns`. |

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

| Concept                        | Canonical owner                                                                                                               | Main source evidence                                                                                                                                                                                                  | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Draft flow lifecycle           | `FlowService`                                                                                                                 | `backend/src/eneo/flows/application/flow_service.py::FlowService`                                                                                                                                                               | Creates, updates, validates, publishes, and unpublishes flows. It should not leak FastAPI or frontend concepts.                                                                                                                                                                                                                                                                                                                              |
| Draft flow persistence         | `FlowRepository` and `flow_tables.py`                                                                                         | `backend/src/eneo/flows/infrastructure/flow_repo.py::FlowRepository.update`, `backend/src/eneo/database/tables/flow_tables.py::Flows`                                                                                                       | `FlowRepository.update` owns optimistic draft revision writes.                                                                                                                                                                                                                                                                                                                                                                               |
| Package import lifecycle       | `FlowPackageEnvelope`, import planner/resolver, `FlowPackageInstallService`, `FlowPackageImportRepository`, and central audit | `backend/src/eneo/flow_packages/`, `backend/src/eneo/database/tables/flow_tables.py::FlowPackageImports`                                                                                                                                  | One reviewed checksum, target state, and mapping decision reaches mutation; successful operational rows follow their Flow, failed rows follow their space, and central audit owns post-deletion provenance.                                                                                                                                                                                                                                  |
| Published snapshot shape       | `published_definition.py`                                                                                                     | `backend/src/eneo/flows/published_definition.py::build_published_definition_json`, `backend/src/eneo/flows/published_definition.py::parse_verified_published_definition`, `backend/src/eneo/flows/published_definition.py::parse_published_runtime_steps` | Build and parse published definitions here. Do not read mutable draft steps during runtime.                                                                                                                                                                                                                                                                                                                                                  |
| Runtime consumer contract      | `FlowRunContractService`                                                                                                      | `backend/src/eneo/flows/flow_run_contract_service.py::FlowRunContractService.get_run_contract`                                                                                                    | The run contract owns final output, form fields, runtime step inputs, upload limits, review requirements, and template readiness.                                                                                                                                                                                                                                                                                                            |
| Runtime-safe Flow projection   | `FlowAssembler.to_runtime_public`                                                                                             | `backend/src/eneo/flows/api/flow_assembler.py::FlowAssembler.to_runtime_public`                                                                                                                                                                     | Adds paths for run contract, uploads, run creation, review, evidence, and artifacts.                                                                                                                                                                                                                                                                                                                                                         |
| Flow API access context and action policy | `FlowAccessContext`, `resolve_flow_access_context`, and `flow_access_policy.py`                                  | `backend/src/eneo/flows/api/flow_access_context.py::FlowAccessContext`, `backend/src/eneo/flows/api/flow_access_context.py::resolve_flow_access_context`, `backend/src/eneo/flows/flow_access_policy.py::FlowActionRequirement` | The request-scoped access owner loads the Flow, applies tenant/space scope and optional actor context, and delegates action eligibility to the canonical policy. Routers translate typed failures; `flow_api_common.py` does not own access resolution. |
| Run creation and dispatch      | `FlowRunService`                                                                                                              | `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService.create_run`                                                                                            | Loads the published definition, validates input, enforces idempotency and concurrency, persists run and preseeded steps.                                                                                                                                                                                                                                                                                                                     |
| Worker composition and recovery entry points | `runtime/tasks.py` and `runtime/celery_app.py` | `backend/src/eneo/flows/runtime/tasks.py::execute_flow_run`, `backend/src/eneo/flows/runtime/tasks.py::_execute_flow_run_task`, `backend/src/eneo/flows/runtime/tasks.py::reconcile_stale_running_runs`, `backend/src/eneo/flows/runtime/tasks.py::redispatch_stale_queued_runs`, `backend/src/eneo/flows/runtime/celery_app.py::create_flow_celery_app` | The Celery boundary parses typed dispatch payloads, constructs the task-local composition root, invokes the runtime, contains escaped failures through secondary terminalization, and exposes the scheduled recovery adapters. Application services and repositories own run and recovery semantics. |
| Runtime execution loop         | `FlowRunExecutor`                                                                                                             | `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute`, `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute_claimed`                                                                                                                                                                      | Parses published runtime steps, claims step results, creates attempts, invokes StepHandlers, opens review, inserts webhook delivery intents, and finalizes runs.                                                                                                                                                                                                                                                                             |
| Output-mode behavior           | `FlowRunExecutor._build_step_handler` and the `runtime/step_handlers` classes                                                  | `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor._build_step_handler`, `backend/src/eneo/flows/runtime/step_handlers/`                                                                                                    | The executor constructs a handler by matching the closed `FlowOutputMode` enum; there is no handler registry. Add a handler class and an exhaustive match case, then update the construction guard.                                                                                                                                                                                                                                           |
| Output-type policy             | `runtime/output_formats`                                                                                                      | `backend/src/eneo/flows/runtime/output_formats/base.py::OutputFormatSpec`                                                                                            | `output_type` owns prompt instructions, native JSON-mode preference, validation/rendering requirements, and renderer selection.                                                                                                                                                                                                                                                                                                              |
| Persisted step text interpretation | `domain/step_output.py`                                                                                                   | `backend/src/eneo/flows/domain/step_output.py::interpret_step_text`                                                                                                                                                                       | Owns inline-versus-file-backed text metadata and rejects malformed overflow markers. It performs no file I/O; complete file-backed text remains behind the existing result-file owner.                                                                                                                                                                                                                                                       |
| Byte rendering                 | `runtime/document_rendering` and renderer deps                                                                                | `backend/src/eneo/flows/runtime/output_formats/base.py::RenderDocumentFn`, `backend/src/eneo/flows/runtime/output_runtime.py::OutputRuntimeDeps`                                                                                                     | Renderer functions are leaf adapters. Keep DOCX/PDF/Markdown libraries out of executor and step handlers.                                                                                                                                                                                                                                                                                                                                    |
| Runtime output artifacts       | `output_runtime.py`                                                                                                           | `backend/src/eneo/flows/runtime/output_runtime.py::process_typed_output`, `backend/src/eneo/flows/runtime/output_runtime.py::_persist_rendered_artifact`                                                                                                         | Persists rendered artifact bytes through the runtime principal owner fields.                                                                                                                                                                                                                                                                                                                                                                 |
| Webhook delivery outbox        | `FlowRunWebhookDeliveryRepository` and `FlowRunWebhookDeliveryService`                                                        | `backend/src/eneo/flows/infrastructure/flow_run_webhook_delivery_repo.py::FlowRunWebhookDeliveryRepository`, `backend/src/eneo/flows/runtime/flow_webhook_delivery.py::FlowRunWebhookDeliveryService`                                                                                  | Executor only inserts delivery intents. The repository owns the tenant-scoped, ordered, secret-free public read projection; the outbox worker owns claims, delivery, retries, dead-lettering, and finalization.                                                                                                                                                                                                                                |
| Runtime lifecycle audit outbox | `FlowRunAuditOutboxRepository` and `FlowRunAuditOutboxDeliveryService`                                                        | `backend/src/eneo/flows/infrastructure/flow_run_audit_outbox_repo.py::FlowRunAuditOutboxRepository`, `backend/src/eneo/flows/application/flow_run_audit_outbox_delivery.py::FlowRunAuditOutboxDeliveryService`                                                                          | Lifecycle audit is committed runtime state and is delivered outside tenant audit feature flags. The repository owns bounded dead-letter listing plus the locked generation compare-and-swap; the service owns the atomic redrive and operator audit.                                                                                                                                      |
| Evidence and artifacts         | `FlowRunEvidenceService`, `flow_run_evidence_bundle.py`, `flow_run_evidence.py`, and `flow_run_export_json.py`                 | `backend/src/eneo/flows/application/flow_run_evidence_service.py::FlowRunEvidenceService`, `backend/src/eneo/flows/application/flow_run_evidence_bundle.py::build_evidence_bundle`, `backend/src/eneo/flows/application/flow_run_evidence_bundle.py::redact_evidence_bundle`, `backend/src/eneo/flows/application/flow_run_evidence.py::build_debug_export`, `backend/src/eneo/flows/application/flow_run_export_json.py::render_evidence_json_export` | The service owns access checks, coherent loading, artifact availability, and export orchestration. The bundle module owns canonical assembly and redaction; debug and JSON export modules own their typed projections. |
| Retention control plane        | Nullable tenant columns, `FlowClassificationRetentionPolicyService`, and `DataRetentionService`                               | `backend/src/eneo/database/tables/tenant_table.py::Tenants`, `backend/src/eneo/flows/application/flow_classification_retention_policy_service.py::FlowClassificationRetentionPolicyService`, `backend/src/eneo/data_retention/infrastructure/data_retention_service.py::DataRetentionService`  | Tenant and classification rows own independent delete-after, minimum-retention, and no-purge inputs. Settings, Space, and Flow services are adapters that expose configured and effective state. `DataRetentionService` owns one set-based SQL envelope for purge, preview, and effective reads, plus exact-preview/CAS confirmation. Automatic Flow deletion is Off until an organization or matching-classification delete-after value activates the envelope; minimum-retention and no-purge values only block it. |
| Retention tombstones           | `flow_retention_tombstone.py`                                                                                                 | `backend/src/eneo/flows/flow_retention_tombstone.py::FlowRetentionTombstone`, `backend/src/eneo/flows/flow_retention_tombstone.py::append_retention_tombstone`                                                                                                       | Tombstones preserve cleanup evidence. They do not activate the tenant retention control plane or replace its preview/confirmation contract.                                                                                                                                                                                                                                                                                                  |
| Review checkpoints             | `FlowRunReviewCheckpointService` and `FlowRunReviewCheckpointRepository`                                                      | `backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py::FlowRunReviewCheckpointService`, `backend/src/eneo/flows/infrastructure/flow_run_review_checkpoint_repo.py::FlowRunReviewCheckpointRepository`                                                         | Service owns active checkpoint use cases and API translation. Repository owns checkpoint persistence, state transitions, audit outbox writes, expiry reconciliation, and run-first lock ordering.                                                                                                                                                                                                                                            |
| Step rerun                     | `FlowRunRerunService`                                                                                                         | `backend/src/eneo/flows/application/flow_run_rerun_service.py::FlowRunRerunService`, `backend/src/eneo/database/tables/flow_tables.py::FlowRunRerunOperations`                                                                                              | User and service-key principals may rerun their own runs. Persistence records exactly one typed requester (`requested_by_user_id` or `requested_by_service_id`), and the API policy admits the requested service-key capability while own-run access remains enforced.                                                                                                                                                                                                                                                                                                                                                                             |
| Frontend draft editing         | `FlowEditor.ts`                                                                                                               | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts`                                                                                             | Owns editable fields, step order mutations, active step selection, and metadata writes.                                                                                                                                                                                                                                                                                                                                                      |
| Frontend draft form schema     | `flowFormSchema.ts`, `FlowEditor.ts`, `FlowFormSchemaEditor.svelte`                                                           | `frontend/apps/web/src/lib/features/flows/flowFormSchema.ts::normalizeFlowFormFields`, `frontend/apps/web/src/lib/features/flows/flowFormSchema.ts::buildFlowFormSchemaMetadata`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts::replaceFormSchemaFields`, `frontend/apps/web/src/lib/features/flows/components/FlowFormSchemaEditor.svelte::keepLocalFormSchemaEdits`, `frontend/apps/web/src/lib/features/flows/components/FlowFormSchemaEditor.svelte::reloadStoreFormSchemaFields` | `flowFormSchema.ts` owns normalization and metadata shape; `FlowEditor` owns persistence mutations; `FlowFormSchemaEditor` owns transient editing and conflict choice. Persisted changes arriving during meaningful local edits require an explicit **Keep local edits** or **Reload latest persisted fields** choice. |
| Frontend run contract payload  | `flowRunContract.ts`                                                                                                          | `frontend/apps/web/src/lib/features/flows/flowRunContract.ts`                                                                                   | Builds step file payloads, required field checks, reused input, and create-run intent from generated contract types.                                                                                                                                                                                                                                                                                                                         |
| Frontend run wizard            | `flowRunWizard.ts`                                                                                                            | `frontend/apps/web/src/lib/features/flows/flowRunWizard.ts`                                                                                       | Derives wizard pages and blockers from the backend run contract and file state.                                                                                                                                                                                                                                                                                                                                                              |
| Frontend runtime files         | `FlowRunFileInputState` and `FlowRunDialog`                                                                                   | `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.svelte.ts::FlowRunFileInputState`, `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte::uploadFilesForStep` | Browser runtime-file state belongs to `FlowRunFileInputState`; upload side effects remain in `FlowRunDialog`. |
| Frontend recording lifecycle   | `RecordingSession` and `flowRunRecordingSession.ts`                                                                           | `frontend/apps/web/src/lib/features/audio/recordingSession.ts::RecordingSession`, `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.ts::composeSegmentFilename`, `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.ts::persistRecordingSegment`, `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.ts::scanRecoverableSessionsForSteps` | `RecordingSession` owns recorder lifecycle, rotation, and retry. `flowRunRecordingSession` owns filenames, IndexedDB persistence, and resume/recovery helpers used by `FlowRunDialog`. |
| Frontend run-history polling   | `flowRunHistoryState.ts` and `FlowRunsTable.svelte`                                                                           | `frontend/apps/web/src/lib/features/flows/components/flowRunHistoryState.ts::FlowRunHistoryState`, `frontend/apps/web/src/lib/features/flows/components/flowRunHistoryState.ts::syncFlowRunHistoryPolling`, `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte::loadRuns` | `flowRunHistoryState.ts` owns run-history state, timer scheduling, and the in-flight concurrency guard. `FlowRunsTable` hosts lifecycle effects and presentation; it does not define a second polling owner. |

## Runtime Consumer Journey

Use this journey for public API, SDK, and frontend changes:

1. Discover the published flow through `GET /api/v1/flows/{id}/published/`.
   The response is a runtime-safe projection, including runtime path templates
   from `FlowAssembler.to_runtime_public`. See
   `backend/src/eneo/flows/api/flow_authoring_router.py::get_published_flow_runtime` and
   `backend/src/eneo/flows/api/flow_assembler.py::FlowAssembler.to_runtime_public`.
   This consumer projection currently lives in the authoring router file. Run
   routes are feature-owned by the lifecycle, review, rerun, steps, and evidence
   routers registered through `flow_run_router.py`.
2. Load `GET /api/v1/flows/{id}/run-contract/`. This is the canonical runtime
   input contract. The endpoint describes form fields, runtime input steps,
   upload limits, review steps, final output, and template readiness. See
   `backend/src/eneo/flows/api/flow_upload_router.py::get_flow_run_contract` and
   `backend/src/eneo/flows/flow_run_contract_service.py::FlowRunContractService.get_run_contract`.
3. Upload files through the flow or step runtime-file endpoints. Service-key
   callers may use published runtime uploads only. In the browser,
   `FlowRunFileInputState` owns runtime-file state while `FlowRunDialog` performs
   upload side effects. See
   `backend/src/eneo/flows/api/flow_upload_router.py::upload_flow_runtime_file`,
   `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.svelte.ts::FlowRunFileInputState`,
   and `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte::uploadFilesForStep`.
4. Create the run with `expected_flow_version` from the run contract. `FlowRunService`
   rejects stale versions before it persists the run. See
   `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService.create_run` and
   `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService._prepare_run_creation`.
5. Poll run status and step output. The router documents polling and terminal
   status capability semantics. The web history owner keeps polling state, its
   timer, and the in-flight load guard in `flowRunHistoryState.ts`; the table
   hosts the visibility/lifecycle effects and presentation. See
   `backend/src/eneo/flows/api/flow_run_lifecycle_router.py::get_flow_run`,
   `frontend/apps/web/src/lib/features/flows/components/flowRunHistoryState.ts::syncFlowRunHistoryPolling`,
   and `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte::loadRuns`.
6. If a run pauses at `awaiting_review`, use the active checkpoint endpoint, then
   edit, approve, reject, or resume through the checkpoint paths. See
   `backend/src/eneo/flows/api/flow_run_review_router.py::get_active_flow_run_review_checkpoint`.
7. Download artifacts or evidence through the run artifact/evidence endpoints.
   Artifact content may return gone after retention purges file content. See
   `backend/src/eneo/flows/api/flow_run_evidence_router.py::get_flow_run_evidence` and
   `backend/src/eneo/flows/application/flow_run_evidence_service.py::FlowRunEvidenceService.get_run_artifact_file`.

## Authoring And Publish Journey

The authoring path edits draft state and then freezes a runtime snapshot:

1. The authoring router stays thin: parse request, resolve auth/scope, call
   `FlowService`, assemble a public response.
2. `FlowService.create_flow` and `FlowService.update_flow` normalize metadata,
   validate steps, validate assistant scope, validate security classification,
   and persist through `FlowRepository`. See
   `backend/src/eneo/flows/application/flow_service.py::FlowService.create_flow` and
   `backend/src/eneo/flows/application/flow_service.py::FlowService.update_flow`.
3. `FlowRepository.update` owns the SQL update and draft revision increment. See
   `backend/src/eneo/flows/infrastructure/flow_repo.py::FlowRepository.update`.
4. `FlowService.publish_flow` validates publishability, chooses the next version,
   builds `definition_json`, writes `flow_versions`, and updates
   `flows.published_version`. See
   `backend/src/eneo/flows/application/flow_service.py::FlowService.publish_flow`.
5. Published `definition_json` stores ordered runtime steps and assistant snapshots.
   Do not make runtime code reach back to mutable `flow_steps`. See
   `backend/src/eneo/flows/application/flow_service.py::FlowService._build_definition` and
   `backend/src/eneo/flows/published_definition.py::parse_published_runtime_steps`.

### Package import ownership

The package domain is the strict portable-file boundary. It parses the bounded
`.eneopkg` archive with media type `application/vnd.eneo.package+zip`. The
reader first validates structural ZIP safety and requires `manifest.json`, then
parses the required closed `kind` discriminator. A typed Flow endpoint rejects
Assistant or App kinds before enforcing the exact Flow entry profile and
parsing the Flow payload. A missing manifest remains a structural missing-entry
error. The Flow payload parser rejects unknown nested fields, verifies the
checksum and declared resource references, and validates the deterministic Flow
graph before a plan can be shown. The import planner then resolves that
immutable package against current destination resources and exposes the package
checksum and the load-bearing target state that the importer reviewed.

`FlowPackageProvenance` is the sole durable owner of package omissions. Strict
v1 packages require its `omissions` list: ordinary exports use `[]`; an export
that leaves behind source-local MCP server or tool associations uses exactly
`[{"kind":"mcp_attachment","count":N}]`, where `N` is the positive number of
distinct affected step assistants. The package never carries MCP identities,
configuration, credentials, or content. Provenance participates in the content
checksum, so deleting or changing the advisory invalidates the package. The
same closed omission value is projected by validation and import planning.

Export obtains the count through one tenant-scoped scalar repository query.
The binary response includes
`Eneo-Package-Omitted-Mcp-Assistant-Count` only when the count is positive; the
normal and error CORS paths expose that header. Knowledge replacement guidance
is portable metadata rather than knowledge content: `summary` and
`setup_notes` are limited to 4,000 characters, each source/exclusion list to 20
entries, and each normalized entry to 1,000 characters.

Installation accepts one resolved package command containing that reviewed
checksum, target state, and exact local-resource mappings. It revalidates
mutable destination state before `FlowAuthoringCommandService` creates the
draft; it never silently chooses a replacement model or knowledge source. An
import must map every required model and knowledge dependency to a currently
available local resource. Only a dependency explicitly declared optional may
be omitted, and installation removes only that optional reference from the
draft. An exact retry of a successful checksum, target-state, and mapping
decision returns the existing imported draft. Failed materialization still
rolls back the draft and records a typed terminal failure for the trusted
package.

`FlowPackageImportRepository` stores operational terminal outcomes, not a
permanent registry. A successful import row cascades with its Flow; a failed
row has no Flow and cascades with its space. Import history is therefore not a
space-deletion blocker. Central audit is the sole post-deletion provenance
owner under its configured authorization and retention policy, as decided in
[Flow launch scope and lifecycle](../adr/flow-launch-scope-and-lifecycle.md).
There is no package tombstone, release state, compatibility path, or parallel
retention owner.

The package-import migration is part of the unreleased Flow schema chain. When
its relationship changes, rebuild a disposable branch database and replay to
head using the
[Flow Developer Quickstart](./flow-developer-quickstart.md#practical-editing-rules);
an existing Alembic stamp does not replay an amended revision.

## Runtime Execution Journey

The run lifecycle is database-first:

1. The API calls `FlowRunService.create_run`, which loads the published flow,
   validates the submitted payload, precomputes runtime step input file
   projections, and persists the run with a typed principal identity. See
   `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService.create_run`,
   `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService._prepare_run_creation`,
   and `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService._create_persisted_run`.
2. The router commits before dispatching the worker task, so Celery starts from
   committed run state. See
   `backend/src/eneo/flows/api/flow_run_lifecycle_router.py::create_flow_run` and
   `backend/src/eneo/flows/api/flow_api_common.py::commit_flow_runtime_write_before_response`.
3. The Celery task resolves the principal from `flow_runs.principal_type`,
   `principal_user_id`, or `principal_api_key_id`, validates that the dispatch
   matches persisted run state, and invokes the runtime through the task process
   boundary. See `backend/src/eneo/flows/runtime/tasks.py::_execute_flow_run_task`.
4. The executor parses the published runtime steps, validates assistant snapshots,
   and rebuilds execution state from persisted step results. See
   `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute_claimed`.
5. For each step, the executor checks cancellation/deletion, claims a step result,
   starts an attempt, invokes the resolved StepHandler, persists success or
   failure, and updates the in-memory execution state from persisted results. See
   `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute_claimed`
   and `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor._execute_step`.
6. Review policy pauses the run after the completed step result is persisted.
   HTTP post steps insert webhook delivery intents and return with the run still
   running. See
   `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute_claimed`.
7. When all steps complete, `finalize_run_from_current_results` terminalizes the
   run from persisted result state. See
   `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute_claimed`.

`FlowRunRepository` locks the matching `flow_runs` parent before claiming a
step result or opening a step attempt, then rechecks that the run is still
`queued` or `running` after any lock wait. This parent-before-child order keeps
terminalization and child mutation serialized: a child writer that loses the
race cannot recreate active work after the run becomes terminal. See
`backend/src/eneo/flows/infrastructure/flow_run_repo.py::FlowRunRepository.claim_step_result`
and
`backend/src/eneo/flows/infrastructure/flow_run_repo.py::FlowRunRepository.create_or_get_attempt_started`.

### Provider outcome honesty

`pass_through` and `http_post` are provider-calling output modes. A failure after
their step claim carries the conservative disclosure that provider work may or
may not have started. `AttemptStartProvenance` is not evidence that a provider
call started: every output mode records it, including zero-call `compose_text`.
The transport's typed provider rejection is the only narrower fact used here;
the runtime does not infer call start from exception text and does not repeat an
outcome-unknown request automatically.

`per_source` and `per_item` are whole-step maps, not resumable per-call ledgers.
Rerunning either mode repeats all source or item calls. A caller must therefore
treat an ambiguous failure or `flow_llm_request_timeout` as possible duplicate
provider work and spend, even when no partial output was persisted.

Published mapped definitions are bounded by two separate authoring choices:
`runtime_input.execution_mode: per_source` requires a positive per-step
`runtime_input.max_files`, while an enabled `item_map` requires its own positive
per-step `max_items`. Runtime compares the actual bound source-file or previous-item
count with that ceiling before assistant preparation or the first provider call;
exactly the ceiling is allowed and max+1 rejects the whole step without truncation
or partial calls. Both maps remain sequential and rerun as a whole. The Celery
soft/hard task timeout is their aggregate step deadline; there is no per-source or
per-item timeout owner.

Design note: a bounded pre-provider-infrastructure retry class may be added only
at an adapter boundary that can prove transport invocation did not begin. It
must use a small explicit attempt budget and exclude timeouts, disconnects, and
every other outcome-unknown failure. Until that typed boundary and budget are
implemented, post-claim provider failures remain terminal and are never
automatically repeated. This adds no persisted provider-call marker or second
retry owner.

## Large Runtime Input And Context-Window Policy

Large-input handling is a runtime execution concern, not a static file-count
rule. The risk variable is the token volume packaged into each model call. A
run may attach many small files safely, while one long document may exceed the
selected model's usable context window.

Use two different designs:

| Case                                                                                      | Correct shape                                                                           | Owner                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Exhaustive work where every uploaded source must be read, extracted, cited, or summarized | Map the reader over bounded source units, then compose typed outputs downstream.        | `PassThroughStepHandler` dispatches valid per-source readers and fails closed for invalid `per_source` configuration. See `backend/src/eneo/flows/runtime/step_handlers/pass_through.py::PassThroughStepHandler.execute`. |
| Selective question answering over a large library where only relevant passages matter     | Use knowledge retrieval/RAG so the model receives selected chunks, not the full corpus. | Retrieval stays an assistant/knowledge concern, not a Flow step-input transport.                                                                                                                                                                                   |

For Flow AI Builder-generated multi-source document readers, the current
runtime map is explicit:

1. Builder lowering carries `runtime_input_execution_mode` from the planned step
   into the compiled step draft. See
   `backend/src/eneo/flows/ai_builder/ai_builder_assembly/lower.py::_new_step_draft_from_planned_step`.
2. Builder lowering removes runtime-owned source identity fields from the
   model-facing output guidance while preserving them in the persisted step
   contract. See
   `backend/src/eneo/flows/ai_builder/ai_builder_assembly/lower.py::_assistant_output_fields_for_planned_step`.
3. `PerSourceReader` lists the bound runtime file ids and executes one model
   call per source file. See
   `backend/src/eneo/flows/runtime/step_handlers/per_source_reader.py::execute_per_source_reader`
   and `backend/src/eneo/flows/runtime/step_handlers/per_source_reader.py::_execute_one_source`.
4. The runtime stamps `source_label` and `source_file_id` after each call, so the
   model does not own source identity. See
   `backend/src/eneo/flows/runtime/step_handlers/per_source_reader.py::_source_document_items`.
5. Per-source diagnostics preserve source count, token totals, per-source token
   records, input text previews, and extraction diagnostics. See
   `backend/src/eneo/flows/runtime/step_handlers/per_source_reader.py::_assemble_per_source_output`,
   `backend/src/eneo/flows/runtime/step_handlers/per_source_reader.py::_per_source_runtime_metadata`,
   and `backend/src/eneo/flows/runtime/step_handlers/per_source_reader.py::_per_source_call_metadata`.

`Underlag till text` / source-material bindings are bounded inter-step dataflow.
They are not the mechanism for transporting a large corpus through one prompt.
Use targeted step references and typed JSON contracts for downstream facts, not
`all_previous_steps` as a raw document-text bus.

Runtime measures the packaged prompt for each assistant call against the selected
model's usable context window before sending it to the provider. Oversized calls
fail with `typed_io_input_exceeds_model_window` and an actionable message naming
the step and token limit. Keep this as an execution-time guard, not a compile-time
token estimator; the same published Flow can run later with different files and
different model settings. See
`backend/src/eneo/flows/runtime/step_execution_runtime.py::_typed_context_window_error`
and `backend/src/eneo/flows/flow_api_error_code.py::FlowApiErrorCode`.

### Degraded knowledge retrieval

`rag_retrieval.py` is the canonical owner of retrieval outcomes. An attempted
lookup that returns no chunks has status `no_chunks`, distinct from a successful
non-empty result, a skipped lookup, a timeout, or an exception. The runtime emits
bounded diagnostics without copying the retrieval query: `rag_retrieval_no_chunks`
for an empty result and `rag_retrieval_query_truncated` when query derivation had
to cap input at 2,048 characters. The complete query remains absent from those
diagnostics; `rag.query_derivation` records only the strategy, truncation flag,
and bounded query length.

`output_config.retrieval_policy` is valid only for the retrieval-plus-completion
handlers: `pass_through` and `http_post` (whose handler delegates completion
before it creates an outbound delivery intent). Those steps remain best-effort
when the policy is omitted or is
`{"version": 1, "mode": "best_effort"}`. With
`{"version": 1, "mode": "fail_closed"}`, missing retrieval service or knowledge,
blank retrieval input, query truncation, `no_chunks`, `timeout`, and `error` stop
the affected completion call before its provider I/O. In multi-source or
per-item execution, earlier calls may already have completed. The failed step
result and attempt input payload retain the bounded RAG metadata and diagnostics
before the run is terminalized;
completed best-effort steps retain the same fields and the attempt provenance
retains the exact retrieved passages. Guard diagnostics stay in the immutable
attempt input and current step-result projection instead of being copied into
provenance. Debug and evidence normalization preserve additive RAG fields.
This reuses the published step `output_config`, step-result/attempt persistence,
and evidence owners; it adds no setting, query, lock, migration, or background
process.

### Attempt evidence ownership

`step_result_builder.py` constructs immutable attempt-input and terminal
provenance projections alongside the mutable step-result projection. The
executor supplies runtime facts and orchestrates persistence. Before provider
work, the repository locks the attempt and merges a strict v1 input envelope
containing the start snapshot, the exact resolved runtime input, every prepared
call's question, effective prompt and assistant-context version, plus one shared
initial and optional capability-fallback model configuration. The runtime
dispatches that frozen plan instead of reconstructing it. Terminalization adds
resolved input only for paths that never reached provider-call activation and
cannot silently replace any recorded field.

| Fact | Canonical owner | Other retained projection | Explicitly not retained in attempt provenance |
| ----------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Exact execution input and original output | Immutable `flow_step_attempts.input_payload_json` and `output_payload_json` | The current step result keeps only the runtime value used by downstream execution and review. Its output may legitimately differ after a human edit. | Runtime input, transcription, validation guards, diagnostics, and template output metadata are reconstructed from the attempt payloads. |
| LLM request and attempt-start context                 | Strict `flow-step-attempt-input.v1` envelope in immutable attempt input     | Requested-model/provider attempt columns and current-result prompt/model fields remain transitional runtime/UI projections until the later column migration. | Prompt, model parameters, mapped admission, and attempt-start context are rejected from provenance.                                     |
| Generated and declared artifacts | `flow_run_step_result_files`, joined to `files` | The current result may contain file-backed output metadata needed to interpret its text. | Artifact identity, checksum, size, source, and availability are never copied into provenance. |
| Provider-call lifecycle and token usage | Relational `flow_provider_calls` | Attempt and current-result scalars remain transitional runtime summaries until the typed-owner convergence removes them. | The retired JSONB token-receipt document is rejected as corrupt instead of becoming a fallback authority. |
| Retrieved knowledge | `RetrievedKnowledgeEvidence` inside attempt provenance | The current result carries citation source identity without passages so later steps can inherit source context. | Verbatim passages have no second copy. |
| Raw completion, tool calls, and citation observations | Attempt provenance | None. These facts cannot be reconstructed from the sanitized output. | None. |
| Published HTTP behavior | Immutable published definition plus attempt input/output | None. | HTTP mode and presence flags are derived rather than persisted again. |

The current attempt-provenance schema is `flow-attempt-provenance.v3`; the
immutable attempt-input schema is `flow-step-attempt-input.v1`. Because Flows are
not deployed, retired provenance or unversioned input shapes have no compatibility
reader: an old or malformed document is exported with an explicit corruption
marker. Retention purge markers remain a separate typed state and must never be
reported as `not_tracked` or `corrupt`.

## Step Behavior And Output Format

Flows separate the two axes that used to drift together:

| Axis                | Owner                                                                  | What it owns                                                                                                                                                                                     | What it must not own                                                                     |
| ------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `output_mode`       | `FlowRunExecutor._build_step_handler` and StepHandler classes          | Runtime behavior: the executor matches `FlowOutputMode` and constructs the corresponding handler to call the LLM, skip it for transcription, run template fill, or queue a webhook delivery intent. | Prompt instructions, JSON-mode policy, document rendering, or output-type validation.    |
| `output_type`       | OutputFormatSpec registry and specs                                    | Prompt instructions, native JSON object-mode preference, output validation, document rendering requirement, and renderer choice. See `backend/src/eneo/flows/runtime/output_formats/base.py::OutputFormatSpec`. | Step behavior dispatch, run lifecycle, webhook delivery, or review checkpoint lifecycle. |
| OutputRenderer role | `runtime/document_rendering` leaves passed through `OutputRuntimeDeps` | Byte rendering for DOCX/PDF/Markdown-derived artifacts. See `backend/src/eneo/flows/runtime/output_formats/base.py::RenderDocumentFn` and `backend/src/eneo/flows/runtime/output_runtime.py::OutputRuntimeDeps`.                | Business policy, persistence ownership, or a plugin SDK.                                 |

`FlowRunExecutor._execute_step` resolves the StepHandler from `output_mode`.
`step_execution_runtime.py` prepares the assistant call and calls
`process_typed_output`. `output_runtime.py` resolves the OutputFormatSpec from
`output_type` and persists rendered artifacts. See
`backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor._execute_step`,
`backend/src/eneo/flows/runtime/step_execution_runtime.py::prepare_step_execution`,
and `backend/src/eneo/flows/runtime/output_runtime.py::process_typed_output`.

## Stale-running recovery clock

`flow_runs.updated_at` is the accepted stale-running clock. The only legitimate
mid-run reset is the one-shot transcription input patch. With the default
3,600-second task timeout, that late patch can delay stale eligibility to at
most 7,320 seconds (two task hard-timeout windows) after run start, followed by
one further 60-second reconciliation interval before the periodic reconciler
must observe it. This is an accepted bounded risk, not a claim that every run
waits that long.

Introducing `last_progress_at` remains the deletion trigger for this accepted
risk if runtime deadline work needs a clock that excludes incidental row
writes. The fake-clock ceiling proof is
`backend/tests/integration/flows/test_flow_worker_crash_recovery.py::test_updated_at_staleness_clock_has_bounded_transcription_reset_ceiling`.

## Webhook Outbox Lifecycle

HTTP post is durable outbox work:

1. `HttpPostStepHandler` wraps pass-through execution and emits one
   `WebhookDeliveryIntent` with a run, step, attempt, and idempotency key. See
   `backend/src/eneo/flows/runtime/step_handlers/http_post.py::HttpPostStepHandler.execute`.
2. The executor inserts pending delivery rows after the step result is persisted
   and commits before returning `running`. See
   `backend/src/eneo/flows/runtime/executor.py::FlowRunExecutor.execute_claimed`.
3. The webhook repository uses `ON CONFLICT DO NOTHING` for idempotent insert and
   `FOR UPDATE SKIP LOCKED` for delivery claims. See
   `backend/src/eneo/flows/infrastructure/flow_run_webhook_delivery_repo.py::FlowRunWebhookDeliveryRepository.insert_pending_delivery`
   and
   `backend/src/eneo/flows/infrastructure/flow_run_webhook_delivery_repo.py::FlowRunWebhookDeliveryRepository.claim_due_delivery_rows`.
4. `FlowRunWebhookDeliveryService.deliver_due` provides an at-least-once sender
   contract. A claim atomically charges one of five attempts and commits before
   HTTP. An expired below-budget claim can be reclaimed with the same
   `Idempotency-Key`; an expired fifth claim is outcome-unknown, is dead-lettered,
   and fails the run without a sixth POST. HTTP `408` and `429`, `5xx`, and
   transport failures remain bounded-retryable; other `4xx` responses are
   terminal. See
   `backend/src/eneo/flows/runtime/flow_webhook_delivery.py::FlowRunWebhookDeliveryService.deliver_due`
   and
   `backend/src/eneo/flows/infrastructure/flow_run_webhook_delivery_repo.py::FlowRunWebhookDeliveryRepository.claim_due_delivery_rows`.
5. The data model enforces one delivery per `(flow_run_id, step_id, attempt_no)`
   and uses the shared outbox delivery status vocabulary. See
   `backend/src/eneo/database/tables/flow_tables.py::FlowRunWebhookDeliveries`.
6. `DataRetentionService` excludes a run from history purge while any delivery
   remains `pending`. An unclaimed, actively claimed, or expired-claim row is
   still unresolved; claim expiry makes it eligible for a later worker to
   reclaim with the same stable idempotency key. `delivered` and `dead_lettered`
   rows are terminal and do
   not block purge. See
   `backend/src/eneo/data_retention/infrastructure/data_retention_service.py::DataRetentionService`
   and
   `backend/src/eneo/flows/infrastructure/flow_run_webhook_delivery_repo.py::FlowRunWebhookDeliveryRepository.claim_due_delivery_rows`.

This is an at-least-once sender contract: the sender may repeat a POST after a
timeout, connection loss, worker crash, or claim expiry because remote success
may have occurred before the local receipt commit. The opaque `Idempotency-Key`
value is stable only for one Flow run, output step, and step attempt. Eneo does
not verify the receiver's retention or replay semantics, so this wording does
not claim receiver-side idempotency. Receivers must deduplicate repeated requests
carrying that key.

## Lifecycle Audit Outbox Recovery

Flow lifecycle audit delivery is a required local effect, not a best-effort
log. The delivery worker inserts an audit row idempotently with the outbox id,
then marks the outbox row `delivered`; retry exhaustion moves the row from
`pending` to `dead_lettered` and records `dead_lettered_at` as that failure
generation's token.

The super-API-key-only operator API exposes a bounded, offset-paginated list of
dead letters and one redrive command. The repository locks the selected row and
compares both `delivery_status = 'dead_lettered'` and the listed
`dead_lettered_at` token. A missing row returns 404; a non-dead-lettered row or
stale generation returns 409 without mutation or operator audit. A successful
compare-and-swap resets exactly one row to immediately eligible `pending` state,
clears terminal delivery diagnostics, and restores the attempt count to zero.
The application service writes the tenant-scoped SYSTEM operator audit with the
required reason in the same transaction. There is no unaudited resolve path or
manual-SQL recovery contract. See
`backend/src/eneo/flows/api/flow_run_audit_outbox_operator_router.py::redrive_flow_run_audit_outbox_delivery`,
`backend/src/eneo/flows/infrastructure/flow_run_audit_outbox_repo.py::FlowRunAuditOutboxRepository`, and
`backend/src/eneo/flows/application/flow_run_audit_outbox_delivery.py::FlowRunAuditOutboxDeliveryService`.

Unlike terminal webhook delivery, both `pending` and `dead_lettered` lifecycle
audit rows remain run-history purge blockers. After redrive, normal idempotent
delivery creates at most one lifecycle audit, clears the audit-outbox health
flags, and lets the existing run-history policy select the run. Operator
diagnosis and recovery are documented in [Flows runbook](../runbooks/flows.md).

## Runtime Step Identity

Runtime step identity is snapshot-owned:

1. Published definitions contain step ids and ordered runtime steps. Runtime code
   parses these through `parse_published_runtime_steps`. See
   `backend/src/eneo/flows/published_definition.py::parse_published_runtime_steps`.
2. Run creation pre-seeds step results from published step identities. See
   `backend/src/eneo/flows/application/flow_run_service.py::FlowRunService._create_persisted_run`.
3. `flow_step_results.step_id` and `flow_step_attempts.step_id` are non-null,
   with uniqueness per run/step and per run/step/attempt. See
   `backend/src/eneo/database/tables/flow_tables.py::FlowStepResults` and `backend/src/eneo/database/tables/flow_tables.py::FlowStepAttempts`.
4. Rerun, review, evidence, webhook, result-file, and audit rows all refer to the
   runtime snapshot step, not to a mutable draft step lookup at execution time.

Do not reintroduce fallback by `step_order` as runtime truth unless a new board
task proves an unavoidable current caller need. There are no production Flow
users, so legacy compatibility is not a reason by itself.

## Files, Artifacts, Evidence, And Retention

Runtime file ownership is principal-aware:

1. Run creation stores a typed principal identity on `flow_runs`. The database
   check requires either a user principal or a service-key principal, not both.
   See `backend/src/eneo/database/tables/flow_tables.py::FlowRuns`.
2. Rendered output artifacts are stored by `output_runtime.py` with
   `deps.principal.file_owner_fields()` and the run tenant. See
   `backend/src/eneo/flows/runtime/output_runtime.py::_persist_rendered_artifact`.
3. `FlowRunEvidenceService` owns artifact file access, redacted evidence bundles,
   and evidence JSON export. It returns `flow_run_artifact_content_unavailable`
   when retention has purged artifact content. See
   `backend/src/eneo/flows/application/flow_run_evidence_service.py::FlowRunEvidenceService.get_run_artifact_file`
   and
   `backend/src/eneo/flows/application/flow_run_evidence_service.py::FlowRunEvidenceService.export_evidence_json`.
4. `application/flow_run_evidence.py` builds the debug export from the published definition,
   run, step results, attempts, result files, rerun operations, and invalidated
   steps. See
   `backend/src/eneo/flows/application/flow_run_evidence.py::build_debug_export`.
5. `application/flow_run_export_json.py` summarizes retention state and artifact availability
   for evidence exports. See
   `backend/src/eneo/flows/application/flow_run_export_json.py::render_evidence_json_export`.
6. `flow_retention_tombstone.py` defines the tombstone payloads used when run
   evidence or generated artifacts are purged. See
   `backend/src/eneo/flows/flow_retention_tombstone.py::FlowRetentionTombstone`.

Run-history retention eligibility is owned by one SQL envelope in
`DataRetentionService`. Let `A` be the shortest configured organization value
and exact matching-classification delete-after value. With no `A`, automatic
Flow-run deletion is Off even when a Space or Flow has a configured value. With
`A`, the effective delete-after window is the shortest of `A`, Space, and Flow;
child values can tighten the window but cannot activate, loosen, or disable
deletion. Class 3 uses the same exact-match rule as every other classification.

Let `M` be the longest configured organization and exact
matching-classification minimum. A run cannot be selected before both its
effective delete-after time and `M` have elapsed. Either organization or
matching-classification `no_purge` blocks selection. Minimum and no-purge
values are barriers only: they never activate automatic deletion. Purge
selection, administrative preview, and public Flow reads all consume this same
envelope and expose policy conflicts when a delete-after window is shorter than
the mandatory minimum.

Classification policy rows are exact desired state. A row with only a minimum
or no-purge value is valid. Clearing all three values removes the row only
through the previewed, CAS-protected `PUT`; there is no separate classification
policy `DELETE` contract.

Outbox claims, retries, delivery, and dead-letter transitions remain owned by
the webhook repository and service. Pending terminal-webhook intent is
purge-protected regardless of claim timing; terminal delivery state is
purge-permitted at the run-history horizon. Safe candidate locking and final
file/reference cleanup remain separate retention work. Do not fill those gaps
with compatibility code.

## Review, Rerun, And Service-Key Decisions

Review and rerun are separate runtime features:

1. `FlowRunReviewCheckpointService` owns active checkpoint lookup, payload edit,
   approval, rejection, resume, revision checks, and expiry behavior. See
   `backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py::FlowRunReviewCheckpointService`.
2. Review checkpoint API docs tell clients to render from immutable checkpoint
   step snapshots rather than mutable draft definitions. See
   `backend/src/eneo/flows/api/flow_run_review_router.py::get_active_flow_run_review_checkpoint`.
3. `FlowRunRerunService` owns step rerun acceptance, invalidation graph logic,
   input validation, request fingerprinting, and idempotent replay. See
   `backend/src/eneo/flows/application/flow_run_rerun_service.py::FlowRunRerunService`.
4. D1 is resolved in favor of the implemented typed attribution model in
   [ADR: Flow launch scope and lifecycle, decision 15](../adr/flow-launch-scope-and-lifecycle.md#15-service-key-rerun-is-an-explicit-own-run-capability).
   Rerun persistence accepts either a user requester or a service-key requester
   and requires exactly the matching identity field. See
   `backend/src/eneo/database/tables/flow_tables.py::FlowRunRerunOperations`.
5. API policy allows service-key principals for published runtime view/run and
   for own-run review, resume, and rerun when the capability is requested. A
   service key cannot rerun another principal's run. See
   `backend/src/eneo/flows/flow_access_policy.py::FlowActionRequirement` and
   `backend/tests/unittests/flows/test_flow_run_rerun_service.py::test_service_principal_reruns_own_run`.

Current service-key posture: service keys can use the published runtime surface
and their own-run review, resume, and rerun paths with typed service-principal
attribution. Broader cross-principal access remains forbidden.

## API And Frontend Contract Ownership

Backend contract owners:

| Contract surface             | Backend owner                                                       | Frontend/SDK owner                                                               |
| ---------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Published runtime projection | `FlowAssembler.to_runtime_public` and `flow_authoring_router.py`    | `frontend/packages/eneo-js/src/endpoints/flows.js` published/runtime helpers     |
| Run contract                 | `FlowRunContractService` and `flow_upload_router.py`                | `frontend/apps/web/src/lib/features/flows/flowRunContract.ts`                    |
| Runtime file uploads         | `flow_upload_router.py` and file upload service                     | `FlowRunFileInputState` state plus `FlowRunDialog` side effects                  |
| Run lifecycle and polling    | `flow_run_lifecycle_router.py`, `FlowRunService`, `FlowRunExecutor` | `flowRunHistoryState.ts` state/timer/concurrency plus `FlowRunsTable.svelte` lifecycle effects and presentation |
| Review checkpoints           | `flow_run_review_router.py` and `FlowRunReviewCheckpointService`    | `FlowRunReviewCheckpointPanel.svelte` and `flowRuntimeErrorMapping.ts`           |
| Step rerun                   | `flow_run_rerun_router.py` and `FlowRunRerunService`                | Generated SDK rerun request and response types                                   |
| Evidence/artifact export     | `FlowRunEvidenceService` and evidence router                        | `FlowRunEvidence.svelte`, evidence actions, and SDK evidence/artifact helpers    |

API rules:

1. Public errors go through `GeneralError` response metadata and Flow API error
   helpers. Shared run forbidden-response metadata lives in the same owner. See
   `backend/src/eneo/flows/api/flow_api_common.py::error_response`.
2. Scope and published-flow requirements belong in `enforce_flow_scope`,
   `resolve_flow_access_context`, and `flow_access_policy.py`. See
   `backend/src/eneo/flows/api/flow_access_context.py::resolve_flow_access_context` and
   `backend/src/eneo/flows/flow_access_policy.py::FlowActionRequirement`.
3. Frontend runtime input payload construction belongs in `flowRunContract.ts`,
   not in Svelte components. Components should consume the generated contract
   and call these helpers. See
   `frontend/apps/web/src/lib/features/flows/flowRunContract.ts`.
4. Frontend draft step order and metadata writes belong in `FlowEditor.ts`, not
   in step-list components. See
   `frontend/apps/web/src/lib/features/flows/FlowEditor.ts`.
5. Recorder lifecycle, rotation, and retry belong to `RecordingSession`.
   Segment filenames, IndexedDB persistence, and resume/recovery helpers belong
   to `flowRunRecordingSession.ts`; `FlowRunDialog` consumes both and retains
   upload side effects.
6. Run-history state, polling timers, and the in-flight load guard belong to
   `flowRunHistoryState.ts`. `FlowRunsTable.svelte` hosts lifecycle effects and
   presentation rather than creating another polling owner.
7. Form-schema normalization and metadata shape belong to `flowFormSchema.ts`,
   persistence mutations to `FlowEditor`, and transient editing/conflict choice
   to `FlowFormSchemaEditor`. Meaningful local edits cannot be overwritten by a
   persisted update without an explicit keep-local or reload-latest choice.

## Architecture Guard Tests

Run these when changing the named surface:

| Surface                                                     | Guard or test                                                                                                                                      |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Flow root package layout and root-growth freeze             | `backend/tests/unittests/flows/test_flow_package_layout.py::test_flow_root_layout_decision_matches_filesystem`                                     |
| No FastAPI exceptions from Flow application/runtime modules | `backend/tests/unittests/flows/test_flow_architecture_guards.py::test_flow_non_api_modules_do_not_raise_fastapi_http_exception` |
| `output_mode` dispatch remains in StepHandlers              | `backend/tests/unittests/flows/test_flow_architecture_guards.py::test_output_mode_literal_branches_only_appear_in_allowlisted_call_sites` and `backend/tests/unittests/flows/test_flow_runtime_step_handlers.py::test_executor_builds_expected_step_handler` |
| `output_type` policy remains in OutputFormatSpecs           | `backend/tests/unittests/flows/test_flow_architecture_guards.py::test_output_type_literal_branches_only_appear_in_allowlisted_call_sites` and `backend/tests/unittests/flows/test_flow_runtime_output_formats.py::test_output_format_registry_is_total_for_flow_output_types` |
| Removed typed-output helpers do not come back               | `backend/tests/unittests/flows/test_flow_architecture_guards.py::test_removed_typed_output_helpers_do_not_reappear` |
| Webhook delivery stays out of the executor                  | `backend/tests/unittests/flows/test_flow_architecture_guards.py::test_executor_does_not_own_webhook_delivery_side_effects` |
| Shared outbox delivery status vocabulary                    | `backend/tests/unittests/flows/test_flow_architecture_guards.py::test_flow_outbox_delivery_status_vocabulary_is_canonical` |
| Document rendering dependencies stay in leaves              | `backend/tests/unittests/flows/test_flow_runtime_output_renderers.py::test_document_rendering_dependencies_stay_in_rendering_leaves` |
| Runtime output format prompt/JSON-mode behavior             | `backend/tests/unittests/flows/test_flow_runtime_output_formats.py::test_native_json_object_mode_matches_current_schema_matrix` |
| Published definition contract                               | `backend/tests/unittests/flows/test_published_definition_contract.py::test_parser_round_trips_definition_and_runtime_steps` |
| Run contract service                                        | `backend/tests/unittests/flows/test_flow_run_contract_service.py::test_get_run_contract_returns_published_inputs_final_output_and_templates` |
| Consumer API contract                                       | `backend/tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps` |
| Worker runtime contract                                     | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py::test_flow_run_created_by_service_executes_to_terminal_worker_state` |
| Webhook outbox delivery                                     | `backend/tests/integration/flows/test_flow_webhook_outbox_delivery.py::test_flow_webhook_delivery_sends_outside_transaction_and_completes_run` |
| Evidence API contracts                                      | `backend/tests/integration/flows/test_flow_evidence_api_contracts.py::test_completed_verified_evidence_projects_redacted_structured_result` |
| Frontend run contract payload helpers                       | `frontend/apps/web/src/lib/features/flows/flowRunContract.test.ts::flowRunContract helpers` |
| Frontend run wizard and blockers                            | `frontend/apps/web/src/lib/features/flows/flowRunWizard.test.ts::flowRunWizard` |
| Frontend file input state                                   | `frontend/apps/web/src/lib/features/flows/components/FlowRunFileInputState.test.ts::FlowRunFileInputState` |
| Frontend runtime upload side effects                        | `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.dom.test.ts::FlowRunDialog` |
| Frontend recording persistence/recovery                     | `frontend/apps/web/src/lib/features/audio/flowRunRecordingSession.test.ts::buildContractSnapshotFromStep` and `frontend/apps/web/src/lib/features/audio/recordingSession.test.ts::RecordingSession lifecycle` |
| Frontend run-history polling owner                          | `frontend/apps/web/src/lib/features/flows/components/flowRunHistoryState.test.ts::syncFlowRunHistoryPolling` |
| Frontend draft editor ownership                             | `frontend/apps/web/src/lib/features/flows/FlowEditor.test.ts::FlowEditor metadata commands` |
| Form-schema dirty-edit warn-and-choose behavior (TEST-6)    | `frontend/apps/web/src/lib/features/flows/components/FlowFormSchemaEditor.dom.test.ts::FlowFormSchemaEditor conflicts` |

## Where To Change X

| Change                                        | Start here                                                                                     | Guard to run                                                                                                          |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Add or rename a persisted Flow draft field    | `FlowService`, `flow_models.py`, `flow_tables.py`, `backend/alembic/versions`, `FlowEditor.ts` | Alembic migration review, Flow service/router tests, `FlowEditor.test.ts`, generated client update if OpenAPI changes |
| Add a field to the published runtime snapshot | `published_definition.py`, `FlowService._step_to_definition`                                   | `test_published_definition_contract.py`, worker/runtime tests                                                         |
| Change run contract shape                     | `FlowRunContractService` and `flow_upload_router.py`                                           | `test_flow_run_contract_service.py`, `test_flow_consumer_api_contract.py`, generated SDK/frontend tests               |
| Change runtime upload rules or browser upload state/effects | `flow_upload_router.py` and upload service for backend policy; `FlowRunFileInputState` for browser state; `FlowRunDialog` for browser side effects | upload router tests, `flowRunContract.test.ts`, `FlowRunFileInputState.test.ts`, `FlowRunDialog.test.ts`, `flowRunWizard.test.ts` |
| Add an output mode                            | `FlowOutputMode`; its handler class; `FlowRunExecutor._build_step_handler`; applicable `output_modes.py` rules; the enum-derived `flow_tables.py` CHECK (plus a migration only when emitted DDL changes); FCM capability seed and `FCM_VERSION`; generated schema/type propagation; frontend `flowStepTypes.ts` options/policy, `flowStepTransitionPolicy.ts`, affected config/guards and presentation/editor components, and `messages/en.json` plus `messages/sv.json`, as applicable | Existing `test_flow_capability_manifest.py`, `test_flow_runtime_step_handlers.py`, and `test_flow_architecture_guards.py`; generated-contract checks; representative tests for each affected frontend policy/options, transition, config, or presentation owner |
| Add an output type                            | `runtime/output_formats`                                                                       | OutputFormatSpec registry tests, output-type branch guard, document renderer guard if it renders bytes                |
| Change DOCX/PDF rendering                     | `runtime/document_rendering` or `docx_template_runtime.py`                                     | output renderer tests, output runtime tests, template fill runtime tests                                              |
| Change webhook delivery semantics             | `HttpPostStepHandler`, webhook outbox repo/service                                             | webhook outbox delivery tests and executor no-inline-delivery guard                                                   |
| Change run terminalization                    | `FlowRunTerminalizer`, executor, webhook delivery finalization                                 | terminalization, worker contract, audit outbox tests                                                                  |
| Change review checkpoint behavior             | `FlowRunReviewCheckpointService` and review routes                                             | review checkpoint service/router tests and frontend review panel tests                                                |
| Change rerun behavior                         | `FlowRunRerunService` and rerun routes                                                         | rerun service/repository/API tests                                                                                    |
| Change service-key Flow permissions           | `flow_access_policy.py`, `flow_api_common.py`, affected routers                                | service-key permission tests, API contract/OpenAPI tests                                                              |
| Change evidence export                        | `FlowRunEvidenceService`, `application/flow_run_evidence.py`, `application/flow_run_export_json.py` | evidence service/API/export tests                                                                                  |
| Change retention/tombstone semantics          | `DataRetentionService`, `flow_retention_tombstone.py`, retention policy/worker files           | retention tests plus product/data decision receipt                                                                    |
| Change frontend draft step order              | `FlowEditor.ts`                                                                                | `FlowEditor.test.ts`                                                                                                  |
| Change frontend run launch payload            | `flowRunContract.ts`                                                                           | `flowRunContract.test.ts`, `flowRunWizard.test.ts`, relevant component tests                                          |
| Change recording lifecycle, rotation, or retry | `RecordingSession`                                                                            | `recordingSession.test.ts`                                                                                            |
| Change recording filenames, persistence, or resume helpers | `flowRunRecordingSession.ts`; then its `FlowRunFileInputState` and `FlowRunDialog` consumers | `flowRunRecordingSession.test.ts`, `FlowRunFileInputState.test.ts`, `FlowRunDialog.test.ts`                           |
| Change run-history polling state, timer, or concurrency | `flowRunHistoryState.ts`; keep lifecycle effects and presentation in `FlowRunsTable.svelte` | `flowRunHistoryState.test.ts`, then focused `FlowRunsTable` tests                                                     |
| Change form-schema normalization or metadata shape | `flowFormSchema.ts`; use `FlowEditor` for persistence mutations and `FlowFormSchemaEditor` for transient editing/conflict choice | `flowFormSchema.test.ts`, `FlowEditor.test.ts`, `FlowFormSchemaEditor.test.ts`                                        |

## Known Decisions And Compatibility Paths

| Item                                           | Current owner                                                                                             | Status                                                                                                                                                                                                       | Deletion or decision trigger                                                                                                                                           |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Remaining runtime-retention implementation     | `DataRetentionService`, retention policy files, tombstone schema, evidence export                         | Launch policy is recorded. Pending terminal-webhook intent already blocks run-history purge; delivered and dead-lettered intent is purge-permitted at the horizon.                                           | Complete safe candidate locking, whole-run/file finalization, and the recorded retention horizons through focused changes with data/schema preflight.                  |
| Service-key identity for review/rerun (D1)     | `flow_access_policy.py`, `FlowRunReviewCheckpointService`, `FlowRunRerunService`, rerun table constraints | Resolved: review, resume, and rerun support service-key own-run paths; rerun audit state persists exactly one typed requester identity. | Preserve own-run enforcement and typed attribution when changing service-key capabilities; this is not an open data-model decision. |
| Form-schema dirty local edit conflict behavior (TEST-6) | `flowFormSchema`, `FlowEditor`, `FlowFormSchemaEditor`                                             | Ratified: when persisted metadata changes during meaningful local edits, the editor requires the user to choose either **Keep local edits** or **Reload latest persisted fields**. `frontend/apps/web/src/lib/features/flows/components/FlowFormSchemaEditor.dom.test.ts::FlowFormSchemaEditor conflicts` proves both branches and blank-edit negatives. | Revisit only through an explicit product/UX decision with replacement behavior tests; this is not an open launch gate. |
| Browser upload/audio side-effect ownership (D3) | `FlowRunDialog`, `FlowRunFileInputState`, `flowRunRecordingSession`, `RecordingSession`                  | Ratified: `FlowRunFileInputState` owns browser runtime-file state; upload side effects remain in `FlowRunDialog`; `RecordingSession` owns lifecycle/rotation/retry; `flowRunRecordingSession` owns filenames, IndexedDB persistence, and resume/recovery helpers. | Revisit only through an explicit product/frontend decision with replacement behavior tests; do not copy these responsibilities into a second owner. |
| Run-history polling ownership (D3)             | `flowRunHistoryState.ts`, `FlowRunsTable.svelte`                                                           | Ratified: `flowRunHistoryState.ts` owns polling state, timer scheduling, and concurrency; `FlowRunsTable.svelte` hosts lifecycle effects and presentation. | Revisit only through an explicit product/frontend decision with replacement behavior tests; do not introduce a parallel polling store or timer. |
| Evidence export raw/detail policy              | Evidence router and `FlowRunEvidenceService`                                                              | Raw export requires an explicit reason and separate access kind. See `backend/src/eneo/flows/api/flow_run_evidence_router.py::export_flow_run_evidence` and `backend/src/eneo/flows/application/flow_run_evidence_service.py::FlowRunEvidenceService.export_evidence_json`. | Product/security decides whether raw export remains, narrows, or is removed before public launch.                                                                      |

Compatibility paths are not architecture goals. Keep one only when a current
caller, current data, or recorded product decision requires it. Otherwise, create
a Scout/Judge/Worker pair that proves zero need and deletes the weaker path.
