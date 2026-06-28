# Flow Runtime API Contract Gate 0

Date: 2026-06-28

## TL;DR

The runtime endpoint registry is already the right source of truth for route path, method, operation ID, success status, and runtime path projection.
Existing tests already prove registry entries match live FastAPI routes and generated OpenAPI runtime-path examples.
The current gap is smaller: consumer docs catalogs are not forced to mention every runtime endpoint contract across sequences, worked examples, and pitfall rows.
Three endpoint contracts are missing from docs-catalog coverage: `get_published_flow_runtime`, `cancel_flow_run`, and `redispatch_flow_run`.
The implementation lane should be docs/catalog coverage plus one guard test, not new runtime abstractions or JSONB schema changes.

## Evidence Base

| Evidence | Source |
|---|---|
| Runtime endpoint registry lists every public runtime contract | `backend/src/intric/flows/api/flow_runtime_endpoint_registry.py:76` |
| Registry-to-live-route/status/operation-id tests exist | `backend/tests/unittests/flows/test_flow_docs_site_contract.py:2613` |
| Runtime path projection drift test exists | `backend/tests/unittests/flows/test_flow_docs_site_contract.py:2625` |
| OpenAPI runtime path example matches operation paths | `backend/tests/unit/test_flow_openapi_contract.py:1511` |
| Consumer docs sequences exist but only validate referenced endpoints, not all endpoints | `backend/tests/unittests/flows/test_flow_docs_site_contract.py:2584` |
| FAQ pitfall rows are typed docs coverage for reference-depth endpoint behavior | `backend/scripts/flow_consumer_faq_docs.py:34` |
| Integrating guide sequences currently cover most runtime-path journeys | `backend/scripts/flow_consumer_integrating_flows_docs.py:76` |
| Designing guide covers published contract discovery | `backend/scripts/flow_consumer_designing_flows_docs.py:93` |

## Gate 0 - Endpoint Registry Coverage

`route`, `method/status`, and `operation ID` are already enforced by the registry/live-route tests. `runtime path field` means a field is intentionally projected in `FlowRuntimePathsPublic`; `n/a` means the endpoint is callable directly but is not a per-flow runtime path projection.

| Endpoint contract | FastAPI route exists | Method/status match | Operation ID match | Runtime path field produced | Docs/example | Test |
|---|---:|---:|---:|---:|---:|---|
| `get_published_flow_runtime` | yes | yes | yes | n/a | no | route/OpenAPI only |
| `get_flow_run_contract` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `get_flow_graph` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `upload_flow_runtime_file` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `delete_flow_runtime_file` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `get_flow_run_status_capabilities` | yes | yes | yes | n/a | yes | route/OpenAPI/docs |
| `create_flow_run` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `list_flow_runs` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `get_flow_run` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `get_active_flow_run_review_checkpoint` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `edit_flow_run_review_checkpoint` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `approve_flow_run_review_checkpoint` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `reject_flow_run_review_checkpoint` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `resume_flow_run_review_checkpoint` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `cancel_flow_run` | yes | yes | yes | yes | no | route/OpenAPI only |
| `rerun_flow_run_step` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `redispatch_flow_run` | yes | yes | yes | yes | no | route/OpenAPI only |
| `get_flow_run_evidence` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `export_flow_run_evidence` | yes | yes | yes | yes | yes | route/OpenAPI/docs pitfall |
| `list_flow_run_steps` | yes | yes | yes | yes | yes | route/OpenAPI/docs |
| `generate_flow_run_artifact_signed_url` | yes | yes | yes | yes | yes | route/OpenAPI/docs |

## Gate 1 - API Consumer Journey Matrix

| Journey | Request | Expected response | Data model rows | Idempotency/error behavior | Docs/SDK example | Test |
|---|---|---|---|---|---|---|
| inspect published runtime | `GET /flows/{id}/published/` then runtime paths | published runtime plus path templates | `flows`, `flow_versions` | read-only, not-published/forbidden/not-found errors | missing explicit catalog coverage | route/OpenAPI only |
| inspect run contract | `GET runtime_paths.run_contract` | required inputs, review steps, final output | `flow_versions.definition_json` | stale version guarded at create time | covered | route/OpenAPI/docs |
| upload runtime file | `POST upload_step_runtime_file_template` | uploaded file id | `flow_runtime_uploaded_files`, `files` | file validation errors | covered | route/OpenAPI/docs |
| delete runtime file | `DELETE delete_runtime_file_template` | `204` for unattached abandoned upload | `flow_runtime_uploaded_files` | attached file returns conflict | covered | route/OpenAPI/docs |
| create run | `POST create_run` with `Idempotency-Key` | committed run id/status | `flow_runs`, step input file rows | replay same key/fingerprint; conflict on changed request | covered | route/OpenAPI/docs |
| poll/list run | `GET get_run_template`, `GET list_runs` | run status/result or visible run list | `flow_runs` | service keys list own runs only | covered | route/OpenAPI/docs |
| list step results | `GET list_steps_template` | ordered step outputs/files/errors | `flow_step_results`, result files | read-only auth errors | covered | route/OpenAPI/docs |
| artifact signed URL | `POST artifact_signed_url_template` | signed URL response | `flow_run_step_result_files`, `files` | artifact not found/content unavailable | covered | route/OpenAPI/docs |
| review checkpoint | active/edit/approve/reject/resume templates | checkpoint state transitions and resume result | `flow_run_review_checkpoints`, `flow_runs` | stale revision, active-state, resume idempotency | covered | route/OpenAPI/docs |
| cancel run | `POST cancel_run_template` | cancelled or terminal run response | `flow_runs` | non-terminal only; user-cancelled errors | missing explicit catalog coverage | route/OpenAPI only |
| rerun from step | `POST rerun_step_template` | rerun operation and invalidated steps | `flow_run_rerun_operations`, invalidated steps | stale revision and input override errors | covered | route/OpenAPI/docs |
| redispatch run | `POST redispatch_run_template` | redispatch count | `flow_runs`, worker dispatch state | stale queued recovery, may return zero | missing explicit catalog coverage | route/OpenAPI only |
| evidence/export | `GET evidence_template`, `GET export_evidence_template` | evidence JSON or export bundle | evidence built from run/result/attempt/review/rerun/file rows | evidence permission and export reason errors | covered through results and FAQ pitfall docs | route/OpenAPI/docs |
| retention/purge | retention services/policies | purged debug evidence without orphaned files | run/result/file/audit rows | purge guards and FK behavior | docs schema only | integration retention tests |

## Gate 2 - Runtime JSONB Decision

No JSONB column in this journey needs relationalization for the chosen slice. The missing proof is docs coverage, not data-model ownership.

| Column | Journey use | Pydantic owner | Query/filter need | FK/ownership hidden | Retention/audit need | Decision |
|---|---|---|---:|---:|---:|---|
| `flow_versions.definition_json` | run contract and graph | `PublishedFlowDefinition` | no | no | checksum audit | keep JSONB snapshot |
| `flow_runs.input_payload_json` | create/replay/debug | `FlowRunInputEnvelope` | no | files already relational | retention clears debug data | keep JSONB payload |
| `flow_runs.output_payload_json` | final run output | `FlowRunOutputPayload` | no | result files relational | retention clears debug data | keep JSONB payload |
| `flow_runs.error_json` | terminal failure | `FlowRunError` | no | no | auditable failure | keep JSONB envelope |
| `flow_step_results.input_payload_json` | step debugging | `FlowStepResultInputPayload` | no | files relational | retention clears debug data | keep JSONB payload |
| `flow_step_results.output_payload_json` | step output | `FlowStepResultOutputPayload` | no | result files relational | retention clears debug data | keep JSONB payload |
| `flow_step_results.model_parameters_json` | evidence/provenance | `FlowStepModelParameters` | no | provider-defined | evidence availability | keep JSONB provenance |
| `flow_step_attempts.provenance_json` | evidence/export | `FlowStepAttemptProvenance` | no | result files relational | evidence availability | keep JSONB provenance |
| `flow_step_attempts.input_payload_json` | attempt snapshot | `FlowStepAttemptInputPayload` | no | files relational | retention clears debug data | keep JSONB snapshot |
| `flow_step_attempts.output_payload_json` | attempt snapshot | `FlowStepAttemptOutputPayload` | no | result files relational | retention clears debug data | keep JSONB snapshot |
| `flow_run_review_checkpoints.original_payload_json` | review compare | `ReviewCheckpointOriginalPayload` | no | checkpoint row owns lifecycle | review audit | keep JSONB payload |
| `flow_run_review_checkpoints.current_payload_json` | review edit | `ReviewCheckpointCurrentPayload` | no | checkpoint row owns lifecycle | review audit | keep JSONB payload |
| `flow_run_review_checkpoints.output_contract_json` | review validation | `ReviewCheckpointOutputContract` | no | checkpoint row owns lifecycle | review audit | keep JSONB snapshot |

## Chosen Lane

Lane A, narrowed to docs drift:

- add catalog coverage for the three missing runtime endpoint contracts;
- add one behavior test proving every registry operation appears in consumer docs sequences, worked examples, or typed pitfall rows;
- regenerate docs-site pages;
- do not change runtime behavior, API shape, generated client schema, migrations, or JSONB persistence.

## Acceptance Criteria

- Every `FLOW_RUNTIME_ENDPOINT_CONTRACTS` operation ID is covered by consumer docs catalog sequences, worked-example hops, or typed pitfall rows.
- The generated docs mention published runtime discovery, cancellation, redispatch, and evidence export without creating new API promises.
- Existing registry/live-route/OpenAPI tests still pass.
- No frontend UI, runtime worker, database, or OpenAPI schema changes are made.
