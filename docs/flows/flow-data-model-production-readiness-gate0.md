# Flow Data Model Production Readiness Gate 0

Date: 2026-06-28

## TL;DR

Flow identity, lifecycle, ownership, file, review, rerun, and outbox concepts are already relational.
JSONB is mostly used for dynamic typed payloads, authored sparse config, immutable snapshots, and auditable diagnostics.
The highest-value source change is not wholesale relationalization; it is deleting the unused Builder plan `rejected` status from the domain, DB check, and generated API schema.
The stale risk is in the JSONB ownership registry: `builder_sessions.conversation` and `builder_sessions.planning_state_jsonb` still read as deferred even though typed owners already exist.
The API consumer path is understandable, but OpenAPI/client generation must be kept in sync when public enums move.

## Evidence Base

This inventory is based on direct source review, not graph output:

| Evidence | Source |
|---|---|
| Flow draft, publish, runtime, review, rerun, outbox, and Builder tables | `backend/src/intric/database/tables/flow_tables.py:156` |
| Published definition schema version and checksum builder | `backend/src/intric/flows/published_definition.py:27` |
| Runtime definition checksum verification before execution | `backend/src/intric/flows/runtime/executor.py:613` |
| Published version repository computes checksum on create | `backend/src/intric/flows/infrastructure/flow_version_repo.py:22` |
| JSONB owner registry and generated docs source | `backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py:93` |
| JSONB registry coverage test | `backend/tests/unittests/flows/test_flow_jsonb_ownership.py:42` |
| AI Builder session, conversation, plan, and proposal domain models | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:32` |
| Typed PlanningState persisted in `builder_sessions.planning_state_jsonb` | `backend/src/intric/flows/ai_builder/planning_state.py:1` |
| AI Builder repository validates proposal hash and planning-state snapshots | `backend/src/intric/flows/ai_builder/ai_builder_repo.py:961` |
| Runtime endpoint registry and operation IDs | `backend/src/intric/flows/api/flow_runtime_endpoint_registry.py:76` |
| Run creation idempotency and fingerprint checks | `backend/src/intric/flows/application/flow_run_service.py:223` |
| Review checkpoint lifecycle service | `backend/src/intric/flows/application/flow_run_review_checkpoint_service.py:170` |
| Rerun lifecycle service | `backend/src/intric/flows/application/flow_run_rerun_service.py:122` |

## Gate 0 - ERD And Ownership Inventory

| Table | Product concept | Writer | Readers | Tenant/space owner | Key FKs | JSONB columns | JSONB decision | API consumer surface |
|---|---|---|---|---|---|---|---|---|
| `flows` | Mutable Flow draft and publish pointer | `FlowRepository` | authoring services, runtime contract services, package/export services | `tenant_id`, `space_id` | tenant, space, creator/owner users, published `(flow_id, version)` | `metadata_json` | Keep JSONB: sparse typed authoring metadata normalized by `intric.flows.flow_metadata` | list/inspect/published contract through Flow APIs |
| `flow_steps` | Editable draft step graph nodes | `FlowRepository` and Builder apply path | publish/materialization, authoring validation, package export | `tenant_id` through `flows` | flow, tenant, assistant, composite flow/tenant | `input_contract`, `output_contract`, `input_bindings`, `input_config`, `output_config`, `review_policy` | Keep JSONB: typed authored config validated before publish; no independent lifecycle | inspect Flow definition after publish, not direct runtime mutation |
| `flow_step_dependencies` | Draft graph dependency edges | `FlowRepository` | publish/materialization and graph validation | `tenant_id` through flow | flow, parent step, child step, composite same-flow FKs | none | Already relational because edges have identity and referential integrity | indirectly visible through published graph/contract |
| `flow_versions` | Immutable published Flow runtime snapshot | `FlowRepository` | runtime executor, contract service, run service, package export | `tenant_id` through flow | flow, tenant, unique `(flow_id, version)` | `definition_json` | Keep JSONB with schema version and checksum verification | inspect published Flow, start run, rerun, run history version binding |
| `flow_template_assets` | Authoring-time DOCX templates and placeholder index | `FlowTemplateAssetRepository` | step config validation, template fill runtime | `tenant_id`, `space_id` | flow, tenant, space, file, users | `placeholders` | Keep JSONB: bounded derived index, not separate lifecycle | upload/manage template assets, template-backed run output |
| `flow_resource_bindings` | Tenant-local resource bindings for portable Flow slots | `FlowRepository` | publish/apply/package materialization | `tenant_id`, `space_id` | flow, tenant, local resource id by kind | none | Already relational because authorization/query/FK-like identity matters | Flow authoring and publish resource resolution |
| `flow_runtime_uploaded_files` | Pre-run files uploaded for a published Flow step | `FlowRuntimeUploadRepository` | run input validation, retention, cleanup | `tenant_id` plus user/service principal owner | file, flow/tenant, user/service owner | none | Already relational because file identity, owner, retention, and authorization matter | upload runtime files, delete runtime uploads, bind uploaded files to run input |
| `flow_package_imports` | Package import attempt, plan, mappings, terminal failure | `FlowPackageImportRepository` | package import/apply services, audit | `tenant_id`, `space_id` | tenant, space, actor user, target flow | `import_plan_json`, `selected_mappings_json`, `failure_json` | Keep JSONB: typed import plan/failure snapshots, not queryable sub-entities | package import APIs, not core runtime consumer path |
| `flow_runs` | Runtime execution instance | `FlowRunRepository`, `FlowRunService`, runtime executor | run API, step/result/review/rerun/evidence services | `tenant_id`, `flow_id`, principal owner | flow, tenant, flow version, user/service principal | `input_payload_json`, `output_payload_json`, `error_json` | Keep JSONB: caller/runtime dynamic payloads and typed error envelope | start run, retry idempotent start, poll/get/list run |
| `flow_step_results` | Current result for each run step | runtime executor and rerun service | API projection, review/rerun/evidence/artifacts | `tenant_id`, `flow_run_id` | run/tenant, run/flow, attempt, review checkpoint | `input_payload_json`, `output_payload_json`, `model_parameters_json` | Keep JSONB: dynamic step payload and provider provenance | list step outputs, fetch artifacts/evidence |
| `flow_step_attempts` | Immutable attempt history for each step execution | runtime executor and rerun service | evidence, outbox, diagnostics | `tenant_id`, `flow_run_id` | run/tenant, run/flow, current result | `provenance_json`, `input_payload_json`, `output_payload_json` | Keep JSONB: per-attempt payload/provenance snapshots | evidence/debug history and outbox linkage |
| `flow_run_step_input_files` | Files attached to a run step input | run creation and rerun input services | runtime executor, retention, evidence | `tenant_id`, `flow_run_id` | run/tenant, runtime uploaded file/flow/tenant | none | Already relational because files require identity, authorization, retention | start run with uploaded files, inspect run inputs |
| `flow_run_step_result_files` | Files produced by a run step | runtime executor/artifact services | artifact API, retention, evidence | `tenant_id`, `flow_run_id` | run/tenant, result, attempt, file | none | Already relational because result files have lifecycle and signed URL access | fetch artifacts, signed artifact URLs |
| `flow_run_review_checkpoints` | Human review pause and decision state | runtime executor and review checkpoint service | review API, run resume, audit/evidence | `tenant_id`, `flow_run_id` | run/tenant, run/flow, step result | `original_payload_json`, `current_payload_json`, `output_contract_json`, `next_step_ids_json` | Keep JSONB with table `schema_version`: dynamic review payloads, relational state/revision/decision fields | active checkpoint, edit, approve, reject, resume |
| `flow_run_rerun_operations` | Rerun request and lifecycle | `FlowRunRerunService` | run history, invalidation service, runtime executor | `tenant_id`, `flow_run_id` | run/tenant, run/flow, actor principal | `input_payload_json` | Keep JSONB: rerun override payload is dynamic and tied to operation | rerun from step, idempotent rerun replay/conflict |
| `flow_run_rerun_invalidated_steps` | Steps invalidated by a rerun | `FlowRunRerunService` | rerun diagnostics, status projection | `tenant_id`, `flow_run_id` | rerun operation, run/tenant | `dependency_sources_json` | Keep JSONB: bounded string set derived from graph; row owns invalidation identity | rerun status/history |
| `flow_run_audit_outbox` | Durable run/review lifecycle audit delivery | runtime and review/rerun services | audit delivery worker, observability | `tenant_id`, `flow_run_id` | run/tenant, run/flow, checkpoint | none | Already relational because delivery state, retries, checkpoint refs, and audit queryability matter | indirect evidence/audit trail |
| `flow_run_webhook_deliveries` | HTTP step delivery outbox | runtime webhook delivery repository | delivery worker, diagnostics | `tenant_id`, `flow_run_id` | run/tenant, run/flow, step attempt | none | Already relational because retries, idempotency, claim lease, and dead-letter state matter | indirect HTTP step delivery status |
| `builder_sessions` | Flow AI Builder conversation, target, lock, planning state | AI Builder session/repository/service | Builder router/service/planner | `tenant_id`, `space_id`, actor user | tenant, space, optional flow, latest plan | `conversation`, `planning_state_jsonb` | Keep JSONB but tighten registry to existing typed owners | AI Builder API only, not core Flow runtime consumer path |
| `builder_session_files` | Files attached to an AI Builder session | AI Builder session service | planner/context loader | `tenant_id`, session | session/tenant, file | none | Already relational because files require identity and cleanup | AI Builder upload/context APIs |
| `builder_plans` | Immutable AI Builder proposal snapshot and lifecycle status | AI Builder planner/repository/lifecycle service | apply/revise/list/get plan paths | `tenant_id`, session | session/tenant, latest plan composite FK | `proposal_json` | Keep JSONB: immutable typed proposal snapshot with `spec_hash` drift guard | AI Builder API, public enum appears in generated client |
| `module_registry` | Adjacent module registry state in Flow table module | module registry service | module health/compatibility code | none in table | none | `metadata_json` | Deferred to platform inventory; kept in registry to avoid hidden exclusions | none for Flow runtime consumer |

## Gate 1 - JSONB Decision Matrix

| Column | Pydantic owner | Schema version? | Query/filter need? | FK/identity hidden? | Retention/audit need? | Decision |
|---|---|---|---:|---:|---:|---|
| `flows.metadata_json` | `intric.flows.flow_metadata.FlowMetadata` | owner-validated | no | no | low | keep JSONB |
| `flow_steps.input_contract` | `intric.flows.runtime.step_definition_parser.StepInputContract` | owner-validated | no | no | low | keep JSONB |
| `flow_steps.output_contract` | `intric.flows.runtime.step_definition_parser.StepOutputContract` | owner-validated | no | no | low | keep JSONB |
| `flow_steps.input_bindings` | `intric.flows.runtime.step_definition_parser.StepInputBindings` | owner-validated | no | no, draft graph identity is relational | low | keep JSONB |
| `flow_steps.input_config` | `intric.flows.runtime.step_definition_parser.StepInputConfig` | owner-validated | no | no | low | keep JSONB |
| `flow_steps.output_config` | `intric.flows.runtime.step_definition_parser.StepOutputConfig` | owner-validated | no | no | low | keep JSONB |
| `flow_steps.review_policy` | `intric.flows.flow_review_policy.FlowReviewPolicy` | owner-validated | no | no | medium | keep JSONB |
| `flow_versions.definition_json` | `intric.flows.published_definition.PublishedFlowDefinition` | checksum and embedded `schema_version` | no | no | high | keep JSONB |
| `flow_template_assets.placeholders` | `intric.flows.flow_template_asset_service.TemplateAssetPlaceholders` | owner-validated | maybe exact placeholder validation only | no | low | keep JSONB |
| `flow_package_imports.import_plan_json` | `intric.flow_packages.domain.flow_package_import_plan.FlowPackageImportPlan` | embedded schema version | no | no | medium | keep JSONB |
| `flow_package_imports.selected_mappings_json` | `intric.flow_packages.domain.flow_package_import_record.FlowPackageSelectedMappings` | owner-validated | no | no | medium | keep JSONB |
| `flow_package_imports.failure_json` | `intric.flow_packages.domain.flow_package_import_record.FlowPackageImportFailure` | owner-validated | no | no | high | keep JSONB |
| `flow_runs.input_payload_json` | `intric.flows.flow_run_input_envelope.FlowRunInputEnvelope` | owner-validated | no | file links are relational | high | keep JSONB |
| `flow_runs.output_payload_json` | `intric.flows.runtime.run_outcome.FlowRunOutputPayload` | owner-validated | no | no | high | keep JSONB |
| `flow_runs.error_json` | `intric.flows.flow_run_error.FlowRunError` | embedded schema version | no | no | high | keep JSONB |
| `flow_step_results.input_payload_json` | `intric.flows.runtime.step_result_builder.FlowStepResultInputPayload` | owner-validated | no | file refs are relational | high | keep JSONB |
| `flow_step_results.output_payload_json` | `intric.flows.runtime.step_result_builder.FlowStepResultOutputPayload` | owner-validated | no | result files are relational | high | keep JSONB |
| `flow_step_results.model_parameters_json` | `intric.flows.flow_run_provenance.FlowStepModelParameters` | provider-defined | no | no | medium | keep JSONB |
| `flow_run_rerun_operations.input_payload_json` | `intric.flows.application.flow_run_rerun_service.FlowRunRerunInputEnvelope` | owner-validated | no | file refs are relational | high | keep JSONB |
| `flow_step_attempts.provenance_json` | `intric.flows.flow_run_provenance.FlowStepAttemptProvenance` | embedded schema version | no | no | high | keep JSONB |
| `flow_step_attempts.input_payload_json` | `intric.flows.runtime.step_result_builder.FlowStepAttemptInputPayload` | owner-validated | no | file refs are relational | high | keep JSONB |
| `flow_step_attempts.output_payload_json` | `intric.flows.runtime.step_result_builder.FlowStepAttemptOutputPayload` | owner-validated | no | result files are relational | high | keep JSONB |
| `flow_run_rerun_invalidated_steps.dependency_sources_json` | `intric.flows.flow_run_rerun_graph.RerunInvalidationDependencySources` | owner-validated | no | no | medium | keep JSONB |
| `flow_run_review_checkpoints.original_payload_json` | `intric.flows.application.flow_run_review_checkpoint_service.ReviewCheckpointOriginalPayload` | table `schema_version` | no | no | high | keep JSONB |
| `flow_run_review_checkpoints.current_payload_json` | `intric.flows.application.flow_run_review_checkpoint_service.ReviewCheckpointCurrentPayload` | table `schema_version` | no | no | high | keep JSONB |
| `flow_run_review_checkpoints.output_contract_json` | `intric.flows.application.flow_run_review_checkpoint_service.ReviewCheckpointOutputContract` | table `schema_version` | no | no | high | keep JSONB |
| `flow_run_review_checkpoints.next_step_ids_json` | `intric.flows.infrastructure.flow_run_review_checkpoint_repo.ReviewCheckpointNextStepIds` | table `schema_version` | no | no, step ids are snapshot provenance | medium | keep JSONB |
| `builder_sessions.conversation` | `intric.flows.ai_builder.ai_builder_domain_models.ConversationMessage` array | owner-validated, message-id migration | no | no | medium | keep JSONB but replace deferred registry row with typed owner |
| `builder_sessions.planning_state_jsonb` | `intric.flows.ai_builder.planning_state.PlanningState` | embedded FCM/planner/builder schema versions | no | no | medium | keep JSONB but replace deferred registry row with typed owner |
| `builder_plans.proposal_json` | `intric.flows.ai_builder.ai_builder_domain_models.FlowBuilderProposal` | owner-validated plus `spec_hash` | no | resource bindings are inside proposal but applied relationally on materialization | high | keep JSONB |
| `module_registry.metadata_json` | platform module registry owner pending | deferred | unknown | unknown | medium | defer to platform inventory |

## Gate 2 - API Consumer Journey Matrix

| Journey | Endpoint/API | Data model | Idempotency | Error contract | Docs/SDK example | Test |
|---|---|---|---|---|---|---|
| inspect published Flow | `GET /flows/{flow_id}/runtime-contract`, graph/status capability endpoints | `flows`, `flow_versions`, published definition snapshot | read-only | Flow API error adapter | docs-site generated Flow developer pages | run-contract and docs contract tests |
| upload runtime files | runtime upload/delete endpoints | `flow_runtime_uploaded_files`, `files` | caller can reuse uploaded file id | `flow_run_step_input_*` errors | runtime upload docs and OpenAPI | upload/input validation tests |
| start run | `POST /flows/{flow_id}/runs` | `flow_runs`, `flow_run_step_input_files`, `flow_versions` | `Idempotency-Key` plus fingerprint | run validation errors and idempotency conflict | route description and generated schema | `FlowRunService` idempotency tests |
| retry idempotent start | same run creation endpoint | same as start run | same fingerprint returns existing run | conflict for different fingerprint | route description | idempotency replay/conflict tests |
| poll run | `GET /flows/{flow_id}/runs/{run_id}` | `flow_runs`, current statuses | read-only | not-found/auth errors | OpenAPI response model | run API tests |
| list run history | `GET /flows/{flow_id}/runs` | `flow_runs` indexed by tenant/flow/created | read-only | pagination/filter errors | OpenAPI response model | list runs tests |
| fetch step results | step outputs endpoint | `flow_step_results`, attempts | read-only | not-found/auth/state errors | OpenAPI response model | step output tests |
| fetch artifacts/evidence | artifact signed URL and evidence/export endpoints | `flow_run_step_result_files`, `flow_step_attempts`, evidence summaries | read-only signed URL generation | evidence unavailable/export errors | OpenAPI and docs-site pages | evidence/artifact contract tests |
| review checkpoint | active checkpoint endpoint | `flow_run_review_checkpoints`, `flow_runs` | read-only active checkpoint view | checkpoint unavailable/state errors | OpenAPI response model | review checkpoint tests |
| revise/decide review | edit/approve/reject/resume endpoints | `flow_run_review_checkpoints`, `flow_step_results`, `flow_run_audit_outbox` | decision/resume idempotency keys | revision conflict and rejected/cancelled errors | route descriptions | review checkpoint service/repository tests |
| rerun from step | rerun endpoint | `flow_run_rerun_operations`, invalidated steps, step results | rerun idempotency fingerprint | invalid step/state/conflict errors | OpenAPI response model | rerun service tests |
| retention/purge | retention service/API paths | `flows.data_retention_days`, run/result/file tables | service-level idempotency | purge guard errors | developer docs | retention/FK guard tests |

## Chosen Implementation Lane

Lane B is the best source change for this batch.

Problem: `PlanStatus.REJECTED` and the `builder_plans.status` check allow `rejected`, but source search finds no writer that stores `PlanStatus.REJECTED` or writes `status = 'rejected'` for Builder plans. Review checkpoint rejection is a different runtime concept owned by Flow review services.

Why it matters: `PlanStatus` is public through OpenAPI and the generated TypeScript client. Keeping an unwritten lifecycle state forces API consumers and frontend code to handle a state the product cannot produce.

Current owner: `PlanStatus` in `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:39` and the DB check values in `backend/src/intric/database/tables/flow_tables.py:2058`.

Proposed canonical owner: the same domain enum and table check, with `rejected` removed from the current metadata and the original AI Builder table-creation migration. Flows are unreleased, so the cleaner path is to replay/reset development databases instead of adding a new compatibility migration that adds and then removes the same value.

Reuse, move, merge, delete: delete the unused enum/check value; edit the original table-creation migration rather than adding a follow-up migration; add a direct `PlanStatus` to `BUILDER_PLAN_STATUS_VALUES` sync test; reuse existing plan lifecycle tests and generated OpenAPI/client drift checks; tighten the JSONB ownership registry rows for Builder session state to existing typed owners.

Deliberately not changed: Flow runtime review rejection, run cancellation behavior, API routes, Builder UX, JSONB table shapes, MCP/capability descriptors, frontend UI logic.

Acceptance criteria:

- `PlanStatus` exposes only `proposed`, `approved`, `applied`, and `superseded`.
- `ck_builder_plans_status` matches the Python enum.
- A unit test enforces `tuple(status.value for status in PlanStatus) == BUILDER_PLAN_STATUS_VALUES`.
- The original AI Builder table migration no longer creates a DB check that accepts `rejected`.
- Generated TypeScript `PlanStatus` no longer includes `rejected`.
- JSONB registry has only `module_registry.metadata_json` as deferred inventory.
- Builder JSONB registry `owner_module` consistently means model-defining module for `conversation`, `planning_state_jsonb`, and `proposal_json`.
- Docs-site data schema is regenerated from the updated registry.

Tests and validation:

- focused enum/check-sync and JSONB ownership unit tests;
- Alembic head check;
- docs-site contract test for generated schema docs;
- OpenAPI schema drift check after generated client update;
- ruff, pyright, and import-lint on touched backend paths.

Risk and rollback:

- Runtime risk is low because no Builder plan writer creates `rejected`.
- API risk is intentional: generated clients lose an impossible enum value.
- Migration risk is limited to development databases that already applied the older unreleased branch migration; those databases should reset/replay migrations or manually recreate `ck_builder_plans_status` from the current metadata.
- Rollback means restoring the enum, DB check value, generated client value, and original migration value if product decides to add a real plan rejection workflow later.

## Remaining Production-Readiness Gaps

| Gap | Why it remains | Recommended next action |
|---|---|---|
| Full API consumer golden journey | Existing tests cover parts, but this batch does not add a single upload-run-review-rerun artifact flow | Add one integration contract test after status cleanup lands |
| Platform `module_registry.metadata_json` ownership | Adjacent table is registered but not Flow-owned | Move to a platform data-model inventory |
| Generated SDK examples | OpenAPI schema exists, but examples could be more cohesive | Add docs/examples after API journey test stabilizes |
| Retention purge proof | Retention state is present and relational, but not re-audited in this source slice | Run a focused retention/FK guard review |
