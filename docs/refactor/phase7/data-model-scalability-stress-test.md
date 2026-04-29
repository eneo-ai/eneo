# Phase 7 Data Model And Scalability Stress Test

## TL;DR

Flow and Flow AI Builder should stay on boring relational primitives where lifecycle, permissions, retries, and audit matter.
JSONB remains acceptable for immutable snapshots, provider metadata, heterogeneous user output, and AI Builder planning envelopes, but only behind typed parser/version/corruption handling.
Per-attempt runtime file mapping, step output file artifacts, rerun operations, review checkpoints, and audit/outbox records should be relational.
The first implementation pass should add behavior pins before changing request shape, idempotency fingerprinting, or terminalization.
No sharding, Kafka, or speculative platform machinery is justified by the current evidence.

## Scope

This document covers Flow runtime and Flow AI Builder tables and payloads only. Shared infrastructure is included only when the Flow/AI Builder plan needs a boundary decision.

## Decision Rule

Use a relational table when the data is queried, filtered, sorted, joined, indexed, permissioned, audited, lifecycle-stateful, referenced by other rows, part of idempotency, part of retries, part of human review, or needed for debugging production issues.

Use JSONB only when the data is genuinely heterogeneous, provider-specific, read as a blob, not used for lifecycle decisions, not part of permissions, not audit-critical, and versioned/validated at the boundary.

## JSONB And Dict-Bag Decisions

| Field | Current owner | Current shape | Query/lifecycle use | Risk | Decision | Parser/version plan | Migration impact |
|---|---|---|---|---|---|---|---|
| `flows.metadata_json` at `backend/src/intric/database/tables/flow_tables.py:76-78` | Flow authoring service | `dict[str, Any]` | Form schema, care-data policy, runtime input validation, authoring metadata. | Hidden schema controls execution and policy from an untyped bag. | Split relational core only for policy/lifecycle settings that become queried or permissioned; keep form schema JSONB with parser. | Add `FlowMetadataV1` parser with `form_schema`, `care_data_policy`, and unknown metadata bucket. Reject corrupted policy before publish/run. | Backfill old form field types before deleting legacy normalization. |
| `flow_steps.input_contract` and `output_contract` at `flow_tables.py:124-141` | Flow step contract owner | JSONB contracts/bindings | Runtime validation and AI Builder plan generation. | Shape drift between authored step, published snapshot, runtime, and frontend. | Keep JSONB with typed contract parser; do not normalize until contracts are queried independently. | `FlowStepContractV1`, `FlowInputBindingsV1`, `FlowOutputContractV1`; fail publish on invalid shape. | Parser migration can run before table changes. |
| `flow_steps.input_config` and `output_config` at `flow_tables.py:149-151` | Flow step config owner | JSONB config | HTTP/template/runtime input behavior. | Old config shapes keep repair paths alive. | Keep JSONB for heterogeneous step modes; delete never-shipped fallback shapes after DB proof. | Per-mode parsers: HTTP authored config, runtime input config, template fill config. Include schema version in config. | Backfill `template_file_id` and legacy HTTP config before deleting converter code. |
| `flow_versions.definition_json` at `flow_tables.py:242-243` | Published definition contract | Immutable JSONB snapshot | Runtime execution, evidence, rerun, exported lineage. | Corruption or missing stable IDs breaks execution. | Keep JSONB immutable snapshot plus typed versioned parser; do not normalize published definitions now. | Add first-class schema version in snapshot and parser that rejects missing stable step IDs after backfill. | Existing snapshots need preflight/backfill for `step_id`/`assistant_id`. |
| `flow_template_assets.placeholders` at `flow_tables.py:279-282` | Template asset service | JSONB list | Render validation/display. | Low; small typed list. | Keep JSONB. | Parse as `list[str]`; reject non-strings at inspection/save boundary. | No relational table needed. |
| `flow_runs.input_payload_json` at `flow_tables.py:372-373` | Run creation contract | JSONB envelope | Idempotency, evidence, runtime input. | Top-level `file_ids` duplicates `step_inputs` and hides per-step mapping. | Split relational core for per-step/per-attempt file associations; keep immutable JSONB snapshot for idempotency and evidence. | `FlowRunInputEnvelopeV2` with no top-level `file_ids`; `step_inputs` snapshot mirrors relational mapping for evidence only. Add `input_payload_schema_version`. | Add `flow_run_step_input_files`; update idempotency fingerprint with `request_fingerprint_algo_version`. |
| `flow_runs.output_payload_json` at `flow_tables.py:375-376` | Run terminalization owner | JSONB envelope | Final result display/API/evidence. | Large artifacts or rerun lineage can become hidden blob state. | Keep JSONB for final output summary; relational rows own artifacts, review checkpoints, rerun lineage. | `FlowRunOutputEnvelopeV1`; reject unversioned terminal output after terminalization command lands. | No immediate table split beyond artifact/review/rerun rows. |
| `flow_step_results.input_payload_json` and `output_payload_json` at `flow_tables.py:473-478` | Runtime step result projection | JSONB envelopes | Evidence, rerun, artifact retrieval, UI display. | Current projection can be mistaken for full history after rerun. | Keep JSONB for current projection; attempts and rerun operation rows preserve history. For rerun, default to overwrite the current projection and preserve history in attempts/rerun operations rather than dropping the unique current-row constraint. | `StepInputEnvelopeV2` and `StepOutputEnvelopeV1`; include input/output schema versions or envelope sentinels. | Add result invalidation/supersession metadata before step rerun ships. |
| `flow_step_results.model_parameters_json` and `tool_calls_metadata` at `flow_tables.py:480-493` | Runtime/provider metadata | JSONB provider metadata | Debugging and evidence. | Provider-specific drift. | Keep JSONB with typed shallow parser and raw provider bucket. | `ModelParametersSnapshotV1`, `ToolCallMetadataV1`; unknown provider keys preserved under `provider_metadata`. | No relational table unless dashboards need queryable tool-call fields. |
| `flow_step_attempts.provenance_json` at `flow_tables.py:561-563` | Runtime attempt provenance | JSONB provenance | Debugging, audit-adjacent evidence, rerun lineage. | Corruption hides why a step used files/RAG/templates; some provider fields duplicate relational columns at `flow_tables.py:554-560`. | Keep JSONB as debug/provenance blob; relational columns are canonical for provider/model/token summary. | `FlowAttemptProvenanceV1` with `schema_version`, named corruption error, and export corruption marker. | No table yet; add indexes only if support queries by provenance field become real. |
| `builder_sessions.conversation` at `flow_tables.py:692-696` | AI Builder session repository | JSONB list of messages | Conversation display and planning context. | Message shape drift can break planner state. | Keep JSONB, because it is ordered heterogeneous conversation state. | `ConversationMessage` parser already rejects malformed legacy rows; keep versioned load/save discipline. | Keep behavior pin before deleting `ai_builder_models` barrel imports. |
| `builder_sessions.planning_state_jsonb` and `planning_state_version` at `flow_tables.py:709-716` | AI Builder planning state | JSONB plus version | Optimistic concurrency, planner reconstruction. | Lost update or partial snapshot corrupts planning. | Keep JSONB with strict full-snapshot parser/version. | Existing `PlanningState` validated snapshot remains canonical. | No relational split. |
| `builder_plans.spec_json`, `envelope_json`, `edit_result_json` at `flow_tables.py:799-803` | AI Builder plan store | JSONB plan artifacts | Apply, audit, plan review. | Duplicate spec in envelope can diverge. | Keep JSONB but make `spec_json` canonical; delete legacy duplicate spec copy from rows after preflight. | `BuilderPlanSpecV1`, `PlanEnvelopeV1`, `EditResultV1`; envelope may reference spec hash, not own duplicate spec. | Data cleanup can rewrite envelope rows or ignore duplicate copy with parser. |
| `builder_attachment_observations.observation_json` and `deterministic_signals_json` at `flow_tables.py:839-841` | AI Builder attachment observation cache | JSONB cache entries with natural key | Planning evidence cache and LRU eviction. | Low if version key remains part of primary identity. | Keep JSONB. | Existing observation model plus digest/FCM/pattern version key; reject corrupted cache row and recompute. | No migration beyond cache eviction/backfill. |
| New `flow_run_step_input_files` | Flow run input mapping owner | Relational rows | File authorization, idempotency, rerun, audit/debugging. | Without rows, many-file/many-step/attempt mapping stays hidden inside payload JSON. | Create relational core plus immutable evidence/idempotency JSON snapshot. Scope rows by attempt when rerun can change inputs. | Composite FK `(flow_run_id, tenant_id)`, composite FK `(flow_id, step_id)`, FK `file_id` with `RESTRICT`, unique `(flow_run_id, step_id, attempt_no, ordinal)`, index `(tenant_id, file_id)`. | Backfill new rows from `step_inputs`; top-level `file_ids` migration requires count-query proof and explicit decision. |
| New `flow_run_step_result_files` | Step output artifact owner | Relational rows | Artifact lookup, retention, rerun invalidation, evidence/debugging. | Generated files currently live in output JSON keys and cannot be FK-checked or invalidated by rerun. | Create relational projection for generated output files; JSON output keeps summaries and IDs for evidence. | FK `flow_step_result_id`, FK `file_id` with `RESTRICT`, role (`generated`, `artifact`, `transcript`), superseded marker tied to rerun operation. | Backfill from `generated_file_ids` where safe; preserve historical JSON evidence keys. |
| New `flow_run_rerun_operations` | Runtime rerun owner | Relational rows | Rerun idempotency, invalidation, audit, lineage. | Reusing redispatch hides new semantics and loses the reason/invalidation set. | Create relational operation table. | Operation has normalized input hash, root step, prior/new attempt numbers, invalidated step IDs, requester principal, status, reason, idempotency key. | Required before step rerun endpoint. |
| New `flow_run_review_checkpoints` | Human review owner | Relational rows | Paused runs, edit/revision, resume, audit, frontend. | JSON-only checkpoint would make paused runs hard to query/recover. | Create relational checkpoint table with typed JSON subpayloads for original/edited output. | Explicit state, revision, original output, edited output, next step pointer, decision, requester/reviewer IDs. | Required before human review UI/API. |
| New audit/outbox rows for Flow terminal/review/rerun | Runtime lifecycle owner | Relational outbox | Durable audit, retryable delivery, operations. | Log-only audit loses terminal history under failure. | Use relational outbox in terminalization/review/rerun transactions. | Event schema version and idempotency key per lifecycle transition. | Coordinate with PRD-009. |

## JSONB Version And Corruption Requirements

| Payload | Required hardening |
|---|---|
| `FlowVersions.definition_json` | Add first-class `schema_version` column or equivalent migration-safe owner alongside `definition_checksum`; keep JSON snapshot immutable. |
| `FlowRuns.input_payload_json` / `output_payload_json` | Add envelope schema version and named corruption errors (`flow_run_input_payload_corrupt`, `flow_run_output_payload_corrupt`). Add `request_fingerprint_algo_version` for idempotency changes. |
| `FlowStepResults` JSONB envelopes | Add input/output/model-parameter schema versions or embedded sentinels plus named corruption errors. |
| `FlowStepAttempts.provenance_json` | Parser declares canonical relational columns vs debug blob and emits `flow_attempt_provenance_corrupt` on owned-field corruption. |
| `BuilderPlans.spec_json`, `envelope_json`, `edit_result_json` | Add `jsonb_typeof(...)=object` checks for non-null object envelopes and parser-specific corruption errors. |
| `BuilderAttachmentObservations` JSONB | Keep natural-key versioning and reject/recompute corrupted cache rows. |

## Authoring Graph Consistency

`FlowSteps.input_bindings` at `flow_tables.py:140-141` and `FlowStepDependencies` at `flow_tables.py:186-228` are two representations of the same dependency graph. The long-term owner must be explicit before DAG rerun:

- Preferred default: published `FlowVersions.definition_json` is the runtime graph source for run/rerun because runs are version-pinned; authoring `FlowStepDependencies` is an editable projection updated in the same transaction as step bindings.
- Acceptance: publish writes fail if `input_bindings` and `FlowStepDependencies` drift.
- Rerun must compute from the run's published definition snapshot or version-scoped dependency rows, never from the current draft graph.

## Scalability Edge Cases

| Edge case | Required design response | Evidence / owner |
|---|---|---|
| Many concurrent runs | Claim runs with compare-and-set and indexes on status/updated_at; keep Celery payloads as typed IDs only. | `FlowRunRepository.mark_running_if_claimable` already CASes queued to running at `backend/src/intric/flows/infrastructure/flow_run_repo.py:420-431`; task payload currently passes multiple primitive IDs at `backend/src/intric/flows/runtime/tasks.py:67-77`. |
| Many paused runs | Paused runs need a queryable status and `flow_run_review_checkpoints` indexes by tenant/status/updated_at. | Current run status CHECK lacks review state at `flow_tables.py:397-399`. |
| Many step results per run | Keep `flow_step_results` indexed by run/tenant and add current/superseded semantics for rerun. | Result rows already index run/tenant through FKs and list ordering at `flow_run_repo.py:377-395`. |
| Many files mapped to steps | Use `flow_run_step_input_files` with `(tenant_id, flow_run_id, step_id, attempt_no, position)` index and unique duplicate prevention. | Current mapping is only `step_inputs` JSON plus optional top-level `file_ids` at `flow_run_service.py:399-407`. |
| Large evidence/artifact payloads | Store large artifacts in file/artifact records; JSON envelopes keep IDs and summaries only. | Evidence/export currently scans payload keys including `generated_file_ids` and `file_ids` in `flow_run_export_json.py:461-565`. |
| Duplicate Celery delivery | Claim run/resume/rerun operations with CAS and idempotency keys; duplicate task returns existing operation/result. | Current executor skips terminal runs at `runtime/executor.py:331-340` and claims queued runs at `:342-351`. |
| Worker crash mid-step | Terminalization/reconciliation must close open attempts and audit failure. | Reconciliation currently marks pending steps and fails runs in `runtime/tasks.py:322-358`; terminalization is not yet a single command. |
| Duplicate terminalization | One terminalization command must no-op if already terminal and return existing terminal state. | Current terminal update is direct in executor at `runtime/executor.py:716-731`. |
| Step rerun after completed run | Dedicated rerun operation reopens only affected step projection and records new attempts; final output is recalculated after affected DAG completes. | `FlowStepAttempts` already has `(run, step, attempt_no)` uniqueness at `flow_tables.py:586-590`. |
| Partial rerun with edited inputs | Rerun operation stores normalized edited input and attempt-scoped step file rows; stale downstream evidence is marked invalid. | Existing top-level payload does not model edited step input separately. |
| Audit/event outbox backlog | Outbox delivery can lag but terminal state creation should include durable outbox row or fail before terminal status. | PRD-009 owns the outbox policy. |
| Frontend polling or event refresh pressure | Run detail should expose paused/review/rerun projections so frontend does not infer state from internals. | Frontend currently has manual Flow types at `frontend/packages/intric-js/src/types/resources.d.ts:153`. |
| OpenAPI/client type drift | Backend schema is canonical; handwritten Flow runtime types become generated aliases. | `resources.d.ts` manually defines Flow types while `schema.d.ts` is generated. |

## Non-Goals

- No sharding.
- No Kafka/event-stream rewrite.
- No generic workflow engine abstraction.
- No dual public request shapes for runtime files.
- No worker process waiting for human review.
