# Phase 1b Agent K - Concept Invariants Review

TL;DR:
1. The core architecture risk is not missing code; it is duplicated ownership for statuses, flow definitions, principal identity, evidence, runtime inputs, API types, frontend state, and compatibility paths.
2. Phase 1a broadly agrees on the same root issue: JSON bags and manual frontend/backend mirrors make common changes require scattered edits.
3. The main Phase 1a disagreement is owner selection, so this pass names exact canonical homes and calls out where a new narrow module is better than blessing an existing bag.
4. Pre-production compatibility should be deleted, but only after migration gates for public API fields, persisted row shapes, and cycle-break shims are satisfied.
5. Overall current-state score is 4/10, driven by Single Source of Truth, API Maintainer DX, Frontend State Ownership, and Runtime Reliability.

## Scope And Inputs

This document is Phase 1b Agent K's cross-cutting concept-invariants synthesis. It is documentation-only and intentionally writes only this file.

Required inputs read before writing: `prompt.md`, `AGENTS.md`, `docs/engineering/*.md`, `docs/refactor/phase0/*.md`, `docs/refactor/phase1/README.md`, and Phase 1a outputs `docs/refactor/phase1/01-ai-builder.md` through `docs/refactor/phase1/10-maintainability-interfaces.md`.

Standards applied:

| Standard | Rule Applied |
|---|---|
| `docs/engineering/maintainability-standards.md` | Every important concept needs one canonical home, deletion paths, typed contracts, and reviewable change paths. |
| `docs/engineering/api-design-standard.md` | Routers are HTTP adapters; recommendations must name schema owner, permission owner, error contract, generated-client impact, contract tests, and deletion path. |
| `docs/engineering/frontend-state-standard.md` | Frontend state must have one owner; generated/manual API contracts and derived values cannot drift. |
| `docs/engineering/testing-standard.md` | Tests must protect behavior at real seams, especially runtime idempotency, crash recovery, API contracts, and frontend journeys. |
| `docs/engineering/comment-and-readability-standard.md` | Names should reveal lifecycle phase and canonical owner; comments should explain invariants, not compensate for unclear ownership. |

## Phase 1a Agreements And Disagreements

| Cross-review theme | Agreement | Disagreement / resolution |
|---|---|---|
| Status state machines | Agents B, C, E, F, and J agree run/result/attempt statuses are copied across backend enums, DB constraints, API schemas, frontend resource types, and UI helpers. | Resolution: `backend/src/intric/flows/enums.py` remains semantic owner, but it is insufficient alone. Add lifecycle projections and generate or parity-test DB/API/frontend projections. |
| Published definition JSON | Agents B, E, F, and J agree immutable snapshots are necessary, but broad `dict[str, Any]` parsing is not a contract. | Resolution: create a single domain contract module, proposed `backend/src/intric/flows/domain/flow_definition.py`, called by publication and runtime. Do not preserve `FlowService` plus `step_definition_parser.py` as two owners. |
| Principal/auth/permissions | Agents D, F, and I agree service-key/user principal work is real, but parallel audit/access helpers remain. | Resolution: `FlowPrincipal` owns identity, a typed flow access policy module owns authorization actions, and audit actor mapping has one owner. `flow_api_common.py` should not be blessed as a long-term bag. |
| Evidence/provenance/redaction | Agents B, E, F, and I agree evidence has useful dedicated routes and redaction, but public shape, provenance, and audit behavior are split. | Resolution: keep evidence bundle/redaction/export modules as the concept cluster, but add versioned provenance (`FlowAttemptProvenanceV1`) and typed public response/export contracts. |
| Runtime input/file upload | Agents E, F, J agree `flow_run_step_inputs.py` is a strong normalization owner and `step_input_resolution.py` is the execution resolver. | Resolution: keep the submission/execution split; delete top-level `file_ids` only after explicit data/API/usage gates. |
| Generated/manual API contracts | Agents C, E, I, J agree generated `schema.d.ts` exists but `resources.d.ts`, `flows.js`, and AI Builder protocol types still duplicate shapes. | Resolution: OpenAPI/generated schemas own HTTP contracts. Preserve a narrow handwritten SSE decoder and UI-intent adapters where OpenAPI cannot model the stream. |
| Frontend flow state | Agents A, C, J agree `FlowEditor` is closest to authoring state owner, while AI Builder Driver/Service mirrors state. | Resolution: deepen `FlowEditor`; make `FlowAIBuilderService.svelte.ts` the Svelte state owner and demote `FlowAIBuilderDriver.ts` to transport/SSE decoding. |
| Legacy/compatibility paths | Agents D, G, I, J agree pre-production shims and aliases should be deleted. | Resolution: pure re-export shims are delete candidates after import migration; public fields and persisted-shape fallbacks need data/API gates; cycle-break shims need import-linter guards before deletion. |

## Concept Owner Table

| Concept | Current locations | Problem | Proposed canonical home | Merge/delete path |
|---|---|---|---|---|
| Run/result/attempt status state machines | `backend/src/intric/flows/enums.py:64-85`; DB checks at `backend/src/intric/database/tables/flow_tables.py:397-399`, `backend/src/intric/database/tables/flow_tables.py:503-505`, `backend/src/intric/database/tables/flow_tables.py:570-572`; frontend mirrors at `frontend/packages/intric-js/src/types/resources.d.ts:301`, `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts:40-48`, `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:49-67` | Status values and lifecycle classes are copied, so pause/review/rerun changes require scattered edits. | `backend/src/intric/flows/enums.py` plus a new narrow lifecycle projection module, proposed `backend/src/intric/flows/domain/flow_status_lifecycle.py`. | Generate or parity-test DB CHECK constraints and generated TS statuses; delete duplicated frontend literal sets and backend `_TERMINAL_STATUSES` copies after consumers use projections. |
| Published definition JSON contract | `FlowVersions.definition_json` at `backend/src/intric/database/tables/flow_tables.py:231-243`; publication builds JSON at `backend/src/intric/flows/application/flow_service.py:686-697`; runtime parses broad JSON at `backend/src/intric/flows/runtime/step_definition_parser.py:33-42`; executor checks schema version at `backend/src/intric/flows/runtime/executor.py:1449-1450` | JSON snapshot is necessary, but no single contract module owns version, parser, writer, migration policy, or corruption behavior. | New domain contract module `backend/src/intric/flows/domain/flow_definition.py`; `FlowService` publishes through it and runtime parses through it. | Move `FLOW_DEFINITION_SCHEMA_VERSION`, builder, checksum input, parser, and version validation into the contract module; add `flow_versions.schema_version`; delete ad hoc parser/version checks from services/runtime. |
| Principal identity, access policy, and audit actor identity | `FlowPrincipal` at `backend/src/intric/flows/principal.py:18-119`; DB principal columns and legacy `user_id` at `backend/src/intric/database/tables/flow_tables.py:328-344`; API access bag at `backend/src/intric/flows/api/flow_api_common.py:49-253`; AI Builder local helpers at `backend/src/intric/flows/ai_builder/ai_builder_router.py:128-170` | Identity, authorization action, OpenAPI error examples, access loading, and audit actor mapping are conflated; `FlowPrincipal.audit_actor_fields` and `flow_api_common.audit_actor_kwargs` duplicate actor derivation. | `FlowPrincipal` owns persisted identity; new `backend/src/intric/flows/api/flow_access_policy.py` owns typed actions; one audit actor helper delegates to `FlowPrincipal`. | Replace `required_access: str` with `FlowApiAction`; fold AI Builder scope/edit checks into policy; remove `flow_api_common.audit_actor_kwargs`; drop legacy `user_id` after data migration. |
| Evidence, provenance, redaction, and export | Evidence bundle/redaction at `backend/src/intric/flows/flow_run_evidence_bundle.py:20-130`; debug export at `backend/src/intric/flows/flow_run_evidence.py:17-153`; JSON export at `backend/src/intric/flows/flow_run_export_json.py:37-111`; provenance model at `backend/src/intric/flows/flow_run_provenance.py:33-98`; attempt JSONB at `backend/src/intric/database/tables/flow_tables.py:561-563`; API response at `backend/src/intric/flows/api/flow_models.py:1044-1061` | Evidence has good modules, but public response/export schemas and attempt provenance are still broad dicts and lack versioned parser/migration behavior. | `backend/src/intric/flows/flow_run_evidence_bundle.py` owns evidence assembly; `flow_run_provenance.py` owns `FlowAttemptProvenanceV1`; `flow_run_redaction.py` owns redaction policy. | Add versioned provenance payload and parser; type `FlowStepAttemptPublic.provenance_json`, `FlowRunEvidenceResponse.definition_snapshot`, and export manifest; keep raw forensic snapshots only with explicit schema version. |
| Runtime input/file upload contract | API schemas at `backend/src/intric/flows/api/flow_models.py:410-434`; upload endpoints at `backend/src/intric/flows/api/flow_upload_router.py:22-81`, `backend/src/intric/flows/api/flow_upload_router.py:149-386`; normalization at `backend/src/intric/flows/flow_run_step_inputs.py:38-190`; runtime resolution at `backend/src/intric/flows/runtime/step_input_resolution.py:54-160`, `backend/src/intric/flows/runtime/step_input_resolution.py:391-403`; frontend intent at `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:1-69` | Submission validation, upload endpoints, persisted payload, execution resolution, and frontend run intent are partly aligned but still allow legacy top-level `file_ids`. | `flow_run_step_inputs.py` owns run-submission normalization and validation; `step_input_resolution.py` owns execution-time resolution. Longer term, `flow_run_step_inputs` should become a first-class table. | Keep frontend `flowRunContract.ts` as UI intent adapter but use generated types; delete top-level `file_ids` after data/API migration, zero queued runs with legacy payload, docs/examples removed, and observed external usage window is clear. |
| Generated/manual API contracts | Backend schemas in `backend/src/intric/flows/api/flow_models.py`; generated TS in `frontend/packages/intric-js/src/types/schema.d.ts`; manual TS in `frontend/packages/intric-js/src/types/resources.d.ts:153-366`; wrapper/JSDoc in `frontend/packages/intric-js/src/endpoints/flows.js:1-110`, `frontend/packages/intric-js/src/endpoints/flows.js:412-448`; AI Builder stream typed as string at `frontend/packages/intric-js/src/types/schema.d.ts:34460-34477` | The generated client and handwritten client describe overlapping contracts; generated SSE stream cannot model event payloads, so manual types need a bounded exception. | OpenAPI/Pydantic schemas are HTTP contract owner; `schema.d.ts` is frontend source of truth; a narrow stream-event decoder owns SSE event unions. | Replace `resources.d.ts` Flow aliases with generated schema aliases; type `flows.js` wrapper against generated operations; delete manual AI Builder HTTP schema duplicates; preserve only UI-only intent and SSE decoder types. |
| Frontend flow state | `FlowEditor.ts` authoring state at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:27-120`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:270-330`; AI Builder state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45-81`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:26-70`, mirror at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:266-280`; evidence local records at `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:45-80` | Authoring, AI Builder, run launch, evidence, status, and table polling each recreate backend/domain state locally. | `FlowEditor.ts` owns authoring session; `FlowAIBuilderService.svelte.ts` owns Svelte AI Builder state; `FlowRunLaunchSession` owns run launch; generated evidence types own evidence state shape. | Move route/panel mutations into `FlowEditor` commands; demote driver to transport/SSE decoder; extract run launch mutable workflow from `FlowRunDialog`; delete evidence/status record parsing after generated types land. |
| Legacy and compatibility paths | Backend shims at `backend/src/intric/flows/flow.py:1-37`, `backend/src/intric/flows/flow_service.py:1-5`, `backend/src/intric/flows/flow_run_service.py:1-22`, `backend/src/intric/flows/flow_dispatch.py:1-9`, `backend/src/intric/flows/ai_builder/ai_builder_models.py:1-5`; legacy file adapter at `backend/src/intric/flows/flow_run_step_inputs.py:104-128`; frontend cleanup at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:281-324`; import-linter source still lists shims at `backend/.importlinter:21-45` | Parallel import paths and compatibility branches hide canonical owners; some paths are public/persisted and need migration gates. | Canonical owners are the concrete domain/application/infrastructure/API modules; compatibility inventory is owned by Phase 2/4 deletion PRDs, not by runtime code. | Delete pure re-export shims after import migration; replace `flow_template_validation.py` with an import-linter boundary before deletion; delete persisted-shape fallbacks only after data backfill and zero-row proof. |

## Invariant Ledger

| Invariant | Why it matters | Enforcement | Current violations | Owner |
|---|---|---|---|---|
| Status semantics have one backend owner and generated/parity-tested projections. | Pause/review/rerun states cannot be bolted onto UI or DB separately. | Enum projection tests, DB CHECK generation/parity tests, generated client contract tests. | Manual DB checks and frontend literal sets. | `flow_status_lifecycle.py` plus `enums.py`. |
| Published definitions are versioned domain contracts, not untyped JSON snapshots. | Old runs must execute old snapshots while new publishing evolves safely. | `flow_versions.schema_version`, parser/writer contract tests, corruption behavior tests. | `definition_json: dict[str, Any]`, parser in runtime, builder in service. | `domain/flow_definition.py`. |
| Principal identity is separate from access policy and audit actor rendering. | Service-key/user behavior must be auditable and authorization must be reviewable. | `FlowApiAction` enum, access-policy tests, one audit actor helper. | `flow_api_common.py` bag, AI Builder local scope helpers, legacy `user_id`. | `principal.py` and `flow_access_policy.py`. |
| Evidence exports are redacted by default and provenance is versioned. | Support/compliance traces must be useful without leaking secrets or drifting schema. | Evidence API tests, redaction manifest tests, provenance version parser tests. | Broad provenance JSON and public response dicts. | `flow_run_evidence_bundle.py`, `flow_run_provenance.py`, `flow_run_redaction.py`. |
| Run file mapping is step-scoped at submission and execution. | External consumers need deterministic file-to-step mapping and safe retries. | API contract tests, DB migration checks, runtime resolver tests. | Top-level `file_ids` compatibility path. | `flow_run_step_inputs.py` and `step_input_resolution.py`. |
| Frontend HTTP types come from generated OpenAPI, with explicit handwritten exceptions. | Manual resource types drift and hide backend contract changes. | Generated type import lint, client wrapper tests, no manual Flow runtime aliases except UI/SSE intent. | `resources.d.ts` Flow island and `flows.js` JSDoc `any`. | `schema.d.ts` generation plus narrow adapters. |
| Frontend workflow state has one owner per workflow. | UI behavior should not require chasing mirrored Driver/Service/component state. | Component journey tests through public state owners. | AI Builder Driver/Service mirror; route/panel/editor mutations. | `FlowEditor`, `FlowAIBuilderService`, `FlowRunLaunchSession`. |
| Compatibility paths must have a deletion gate. | Pre-production compatibility should not become permanent architecture. | Kill-list PRD with zero-import/zero-row/usage-window checks. | Shims, legacy adapters, cleanup effects. | Phase 2/4 deletion PRDs. |

## Concept Sections

### 1. Status State Machine

Problem: run, step-result, and attempt lifecycle values are copied across enums, DB CHECK constraints, API models, generated/manual TS types, and frontend helpers.

Why it matters: adding `paused`, `waiting_for_review`, `rerun_requested`, or step-level replay would require coordinated edits in too many places. The system already has status-specific runtime behavior, such as the running-run index at `backend/src/intric/database/tables/flow_tables.py:439-443`, frontend active checks at `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts:40-48`, and table polling at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:189-191`.

Evidence:

| Layer | Evidence |
|---|---|
| Semantic enum | `FlowRunStatus`, `FlowStepResultStatus`, and `FlowStepAttemptStatus` at `backend/src/intric/flows/enums.py:64-85`. |
| DB constraints | Run/result/attempt CHECK constraints at `backend/src/intric/database/tables/flow_tables.py:397-399`, `backend/src/intric/database/tables/flow_tables.py:503-505`, and `backend/src/intric/database/tables/flow_tables.py:570-572`. |
| Frontend manual types | Run and step statuses at `frontend/packages/intric-js/src/types/resources.d.ts:301` and `frontend/packages/intric-js/src/types/resources.d.ts:331`. |
| Frontend behavior | Active/terminal sets at `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts:40-48`; filter counts at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:49-67`. |

Current owner: `backend/src/intric/flows/enums.py` owns status labels, but not lifecycle classifications.

Proposed canonical home: keep status labels in `enums.py`; add `backend/src/intric/flows/domain/flow_status_lifecycle.py` for lifecycle projections such as active, terminal, cancellable, redispatchable, human-waiting, and retryable.

Merge/delete path:

| Merge/delete item | Path |
|---|---|
| DB CHECK values | Generate constraints from enum values or add a parity test that fails when values diverge. |
| Frontend active/terminal sets | Replace with generated status values and one presentation/progress helper. |
| Backend `_TERMINAL_STATUSES` copies | Replace with `flow_status_lifecycle.is_terminal_run_status` and related helpers. |

Acceptance criteria:

- Adding a new run status requires one semantic enum edit, one lifecycle projection decision, one migration generated from or parity-tested against the enum, and generated frontend type updates.
- DB CHECK values, OpenAPI enum values, generated `schema.d.ts`, and frontend status presentation are verified by contract/parity tests.
- `queued`/`running` active semantics and terminal semantics are consumed from one frontend helper.

Tests required:

- Backend unit/parity test: enum values match DB CHECK values for runs, step results, and attempts.
- Runtime behavior test: cancellation, stale reconciliation, completion, and failure use lifecycle projections rather than caller-local sets.
- Frontend component/unit test: run table polling/status filters and progress stats consume generated statuses and handle an unknown/future status safely.

Risk/trade-off: DB CHECK generation can be noisy in migrations. The safer first slice is parity testing plus explicit migration generation in the same PR that adds a status.

Human reviewability impact: reviewers can approve status changes by reading one lifecycle map and one migration instead of chasing enum, SQL, router, API schema, TS resource, and UI helper edits.

Confidence: high.

### 2. Published Definition JSON Contract

Problem: immutable published flow definitions are persisted as raw JSON and read by runtime parsers, but no single contract module owns version, writer, parser, migration policy, or corruption behavior.

Why it matters: old runs must keep executing old snapshots while new authoring features evolve the definition shape. Without one owner, publication can write fields runtime does not validate, and runtime can accept legacy fields without a migration policy.

Evidence:

| Layer | Evidence |
|---|---|
| Persistence | `FlowVersions.definition_json` is `dict[str, Any]` JSONB at `backend/src/intric/database/tables/flow_tables.py:231-243`. |
| Publication writer | `FlowService._build_definition` embeds `schema_version` and step snapshots at `backend/src/intric/flows/application/flow_service.py:686-697`. |
| Runtime parser | `parse_runtime_steps(definition_json: dict[str, Any])` reads raw JSON at `backend/src/intric/flows/runtime/step_definition_parser.py:33-42`. |
| Domain model | `FlowVersion.definition_json` is a broad `JsonObject` at `backend/src/intric/flows/domain/flow.py:115-123`. |
| Version check | Executor only checks integer `schema_version >= 1` at `backend/src/intric/flows/runtime/executor.py:1449-1450`. |

Current owner: split between `FlowService`, `FlowVersions`, `domain/flow.py`, and `runtime/step_definition_parser.py`.

Proposed canonical home: new `backend/src/intric/flows/domain/flow_definition.py`.

Expected responsibilities:

| Responsibility | Contract |
|---|---|
| Writer | Build `PublishedFlowDefinitionV1` from a draft `Flow` and produce canonical JSON for checksum/storage. |
| Parser | Parse and validate a stored definition into runtime DTOs; fail closed with typed domain/application errors. |
| Versioning | Own `FLOW_DEFINITION_SCHEMA_VERSION`, supported versions, migration policy, and corruption behavior. |
| Persistence projection | Store first-class `schema_version` on `flow_versions` in addition to JSON payload. |

Merge/delete path:

- Move `_build_definition`, `_step_to_definition` output shape, and `FLOW_DEFINITION_SCHEMA_VERSION` into the contract module.
- Move runtime parser validation into the contract module or make `step_definition_parser.py` an internal helper called only by the contract module.
- Add `flow_versions.schema_version` and backfill from existing `definition_json["schema_version"]`.
- Delete executor-local version validation after the parser owns it.

Acceptance criteria:

- Publication and runtime both import the same definition contract module.
- The DB row has a first-class `schema_version` column and JSON payload version parity test.
- Old `v1` definitions parse through an explicit supported-version path.
- Corrupt/missing definition JSON has a documented failure mode and API/runtime test.

Tests required:

- Domain contract tests for building/parsing `PublishedFlowDefinitionV1`.
- Repository/data migration test for backfilling `flow_versions.schema_version`.
- Runtime integration test executing a run from a versioned snapshot.
- Contract test proving invalid snapshot shape fails with a typed error, not broad `KeyError`/`BadRequestException` leakage.

Risk/trade-off: creating `flow_definition.py` is new code, but it replaces a parallel implementation rather than adding ceremony. The migration must preserve old snapshots.

Human reviewability impact: future definition-shape changes become one contract diff plus migration/tests, instead of service/runtime/repository/frontend inference.

Confidence: high.

### 3. Principal, Auth, Permissions, Audit Actor, And Idempotency

Problem: the system has a good principal value object, but persisted identity, API access policy, audit actor mapping, AI Builder permission helpers, and idempotency scope still have parallel owners.

Why it matters: service-key runs, user runs, evidence access, artifact access, AI Builder sessions, and idempotent retries must be reviewable as security-sensitive behavior. Today a reviewer must compare `FlowPrincipal`, `flow_api_common`, router-local AI Builder helpers, DB constraints, and run-service idempotency.

Evidence:

| Concept | Evidence |
|---|---|
| Principal value object | `FlowPrincipal` enforces user/service-key identity and exposes DB/file/audit projections at `backend/src/intric/flows/principal.py:18-119`. |
| Legacy persisted identity | `FlowRuns` still stores both principal columns and legacy `user_id` at `backend/src/intric/database/tables/flow_tables.py:328-344`. |
| DB identity constraints | Principal type and identity CHECK constraints at `backend/src/intric/database/tables/flow_tables.py:384-395`. |
| API access bag | `flow_api_common.py` owns error helpers, audit actor mapping, scope enforcement, and access context loading at `backend/src/intric/flows/api/flow_api_common.py:49-253`. |
| Duplicate audit actor mapping | `flow_api_common.audit_actor_kwargs` at `backend/src/intric/flows/api/flow_api_common.py:103-115`; `FlowPrincipal.audit_actor_fields` at `backend/src/intric/flows/principal.py:100-111`. |
| AI Builder local auth | AI Builder edit/scope/session helpers at `backend/src/intric/flows/ai_builder/ai_builder_router.py:128-170`. |
| Idempotency | Request lookup/conflict at `backend/src/intric/flows/application/flow_run_service.py:437-451`; fingerprint scope at `backend/src/intric/flows/application/flow_run_service.py:492-510`; DB indexes at `backend/src/intric/database/tables/flow_tables.py:417-437`. |

Current owner: `FlowPrincipal` is identity owner; `flow_api_common.py` is an accidental access/audit/error bag; `FlowRunService` owns create-run idempotency.

Proposed canonical homes:

| Subconcept | Canonical home |
|---|---|
| Persisted principal identity | `backend/src/intric/flows/principal.py` and `flow_runs` constraints. |
| Flow API action policy | New `backend/src/intric/flows/api/flow_access_policy.py` with `FlowApiAction` enum (`view`, `run`, `manage`, `evidence_view`, `evidence_export_redacted`, `evidence_export_raw`, `ai_builder_use`, `ai_builder_session_access`). |
| Audit actor identity | `FlowPrincipal.audit_actor_fields` plus a single adapter for non-run user objects; delete duplicate route helpers. |
| Run idempotency | `FlowRunService` until a narrower `FlowRunCreationService`/command owner exists; policy must define retention and rerun scope. |

Merge/delete path:

- Replace `required_access: str` in API helpers with `FlowApiAction`.
- Move AI Builder local permission checks into the shared policy module where they are flow/space actions, while preserving session-creator checks as AI Builder session policy.
- Delete `flow_api_common.audit_actor_kwargs` and `flow_router_common.audit_actor_kwargs` after route call sites use principal/audit adapter.
- Backfill/drop legacy `flow_runs.user_id` after `principal_user_id` is complete and read paths no longer need fallback.
- Define idempotency retention and future rerun idempotency before adding step-level rerun endpoints.

Acceptance criteria:

- Flow routes and AI Builder routes use typed actions, not string `required_access`.
- There is one audit actor mapping path for flow-run actors.
- Legacy `user_id` has a migration plan with zero-row/backfill proof and removal test.
- Create-run idempotency documents scope, conflict behavior, retention, and future rerun distinction.

Tests required:

- API authorization matrix tests for user/service-key view/run/manage/evidence actions.
- AI Builder session visibility/access tests through shared policy and session-creator policy.
- Migration/repository test for principal identity after dropping legacy `user_id`.
- Idempotency integration tests: same key/same payload returns run, same key/different payload conflicts, service-key/user scopes do not collide.

Risk/trade-off: pulling auth helpers out of routers can become ceremony if it is generic. Keep the policy module flow-specific and action-oriented.

Human reviewability impact: security-sensitive diffs become a typed policy change plus tests, rather than route-local conditions with duplicated audit mapping.

Confidence: medium-high.

### 4. Evidence, Provenance, Redaction, And Export

Problem: evidence has useful dedicated modules and audit-required routes, but provenance JSON and public evidence/export schemas remain broad and under-versioned.

Why it matters: evidence is the support/compliance surface. It must explain what happened, avoid leaking secrets, and remain stable for generated clients and operators.

Evidence:

| Layer | Evidence |
|---|---|
| Evidence assembly | `EvidenceBundle` and redacted bundle at `backend/src/intric/flows/flow_run_evidence_bundle.py:20-130`. |
| Redaction policy | Redaction policy version and sensitive-key logic at `backend/src/intric/flows/flow_run_redaction.py:8-50`, `backend/src/intric/flows/flow_run_redaction.py:74-108`. |
| Provenance model | `FlowAttemptProvenance` is typed but flexible with many `extra="allow"` submodels at `backend/src/intric/flows/flow_run_provenance.py:33-98`. |
| Attempt storage | `FlowStepAttempts.provenance_json` is JSONB at `backend/src/intric/database/tables/flow_tables.py:561-563`. |
| Runtime writer | Runtime builds attempt provenance at `backend/src/intric/flows/runtime/executor.py:172-233`. |
| Public API | `FlowRunEvidenceResponse.definition_snapshot` and attempt provenance are dicts at `backend/src/intric/flows/api/flow_models.py:1037-1061`. |
| Export response mismatch | Evidence export declares a response model but returns an attachment `Response` at `backend/src/intric/flows/api/flow_run_evidence_router.py:138-251`. |

Current owner: concept cluster exists across `flow_run_evidence_bundle.py`, `flow_run_redaction.py`, `flow_run_provenance.py`, `flow_run_export_json.py`, and `flow_run_evidence_router.py`.

Proposed canonical home: keep the cluster, but assign:

- `flow_run_evidence_bundle.py`: bundle assembly and public evidence projection.
- `flow_run_provenance.py`: versioned attempt provenance contract (`FlowAttemptProvenanceV1`).
- `flow_run_redaction.py`: redaction policy and manifest.
- `flow_run_export_json.py`: export envelope and hash/manifest.

Merge/delete path:

- Add provenance schema version to payload or table column and parse through `FlowAttemptProvenanceV1`.
- Type `FlowStepAttemptPublic.provenance_json` and evidence/export response models, preserving a raw forensic blob only under a versioned `raw` field if needed.
- Align evidence export OpenAPI with actual attachment/download semantics or return JSON according to response model.
- Keep evidence audit-required 503 behavior for direct evidence/export routes; coordinate with observability pass for terminal-run audit swallow behavior.

Acceptance criteria:

- Redacted evidence is default; raw evidence requires explicit access kind and audit.
- Every exported evidence JSON includes evidence schema version, redaction policy version, content hash, and provenance schema version.
- Generated client sees stable evidence/export schema or a correctly documented download endpoint.
- Attempt provenance has a parser and corruption behavior.

Tests required:

- API contract tests for evidence view, redacted export, raw export permission denial/allow, and audit failure 503 behavior.
- Unit tests for redaction policy and manifest paths.
- Provenance parser tests for current payloads, unknown future keys, and corrupt payloads.
- Generated-client/OpenAPI test for export response semantics.

Risk/trade-off: strict provenance typing can reject useful forensic keys. Use versioned typed core with controlled extension fields rather than `dict[str, Any]` everywhere.

Human reviewability impact: evidence changes become contract changes with explicit privacy/security review, not incidental dict shape changes.

Confidence: high.

### 5. Runtime Input And File Upload Contract

Problem: the system has a promising step-scoped runtime input contract, but API request shape, upload endpoints, persisted payload, execution resolver, JS wrapper, and frontend dialog still preserve a legacy top-level file path.

Why it matters: external API consumers need to map files to steps deterministically. Runtime retries and idempotency also depend on a stable, canonical input payload.

Evidence:

| Layer | Evidence |
|---|---|
| API request | `StepRunInput.file_ids`, `FlowRunCreateRequest.step_inputs`, and legacy top-level `file_ids` at `backend/src/intric/flows/api/flow_models.py:410-434`. |
| Run contract/upload endpoints | Run contract and upload routes at `backend/src/intric/flows/api/flow_upload_router.py:22-81`, `backend/src/intric/flows/api/flow_upload_router.py:149-386`. |
| Submission normalization | `build_runtime_step_input_specs`, `normalize_step_inputs_payload`, legacy adapter, and validation at `backend/src/intric/flows/flow_run_step_inputs.py:38-190`. |
| Persisted payload | `FlowRunService.create_run` writes `step_inputs` and still writes top-level `file_ids` when provided at `backend/src/intric/flows/application/flow_run_service.py:399-407`. |
| Runtime resolver | Execution resolves step-scoped input first, then step-1 top-level `file_ids` fallback at `backend/src/intric/flows/runtime/step_input_resolution.py:391-403`. |
| Frontend intent adapter | `flowRunContract.ts` imports flow run types and builds `step_inputs` at `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:1-69`. |

Current owner: `flow_run_step_inputs.py` owns submission normalization; `step_input_resolution.py` owns runtime resolution; `flow_upload_router.py` owns HTTP upload surface.

Proposed canonical home: preserve the split:

- `flow_run_step_inputs.py`: submission contract, validation, file ownership checks, legacy adapter until deleted.
- `step_input_resolution.py`: execution-time file loading, transcription/runtime metadata, and missing-file failure.
- Future data model: `flow_run_step_inputs` table for first-class file associations.

Merge/delete path:

- Keep `flowRunContract.ts` as frontend UI-intent adapter, but import generated types from `schema.d.ts` rather than manual `resources.d.ts`.
- Add migration path from payload-only `step_inputs` to a first-class table if Agent F PRD chooses that design.
- Delete top-level `file_ids` only after all gates pass:
  - OpenAPI and docs/examples no longer show `file_ids`.
  - `intric-js` no longer accepts `file_ids` in new create-run helper.
  - DB query proves zero queued/running runs with top-level `input_payload_json.file_ids`.
  - Access logs or API telemetry show no external top-level `file_ids` usage over the agreed window.
  - Runtime resolver no longer needs step-1 fallback.

Acceptance criteria:

- Public run creation has one canonical step-scoped file mapping shape.
- Upload endpoints and run creation share the same step ID validation and file ownership policy.
- Legacy fallback has an owner, telemetry/usage gate, and deletion PRD.
- Idempotency fingerprint uses canonical normalized step input payload.

Tests required:

- API consumer contract: get run contract, upload runtime file for step, create run with `step_inputs`, reject unknown/disabled step, reject inaccessible file.
- Runtime integration: execute run with step-scoped files and prove resolver uses the intended step.
- Legacy migration test: top-level `file_ids` still works until deletion gate, then fails with a clear error after deletion.
- Frontend component/journey test for run dialog building `step_inputs`.

Risk/trade-off: immediate deletion would break public API consumers if any exist. The repo is pre-production, but this field is already a documented route/client surface, so deletion should still be gated.

Human reviewability impact: future file-mapping changes become a contract/data-model diff rather than coordinated edits in router, service, runtime resolver, JS wrapper, and dialog.

Confidence: high.

### 6. Generated And Manual API Contracts

Problem: backend Pydantic/OpenAPI schemas, generated `schema.d.ts`, manual `resources.d.ts`, `flows.js` JSDoc, and AI Builder `protocol.ts` define overlapping Flow concepts.

Why it matters: manual client types can pass frontend type checks while drifting from backend response models. The flow-scoped frontend diagnostic at `frontend/packages/intric-js/src/endpoints/flows.js:440` already shows wrapper typing and request shape are inconsistent.

Evidence:

| Layer | Evidence |
|---|---|
| Backend runtime schemas | `FlowRunCreateRequest`, `FlowRunPublic`, `FlowInputPolicyPublic`, and `FlowRunStepPublic` at `backend/src/intric/flows/api/flow_models.py:410-523`. |
| Generated schema | `schema.d.ts` exists and includes operation/schemas; AI Builder stream response is `text/event-stream: string` at `frontend/packages/intric-js/src/types/schema.d.ts:34460-34477`. |
| Manual resource island | Comment says Flow types are manually defined until OpenAPI schema is generated at `frontend/packages/intric-js/src/types/resources.d.ts:153`; run/status/step types at `frontend/packages/intric-js/src/types/resources.d.ts:295-366`. |
| JS wrapper | `flows.js` uses JSDoc `any`, manual normalization, and deletes `flow_id` before POST at `frontend/packages/intric-js/src/endpoints/flows.js:1-110`, `frontend/packages/intric-js/src/endpoints/flows.js:412-448`. |
| Frontend evidence local types | Evidence component uses `Record<string, unknown>` for run/snapshot/attempts at `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:45-80`. |

Current owner: split between backend Pydantic models, generated schema, manual resource definitions, JS wrapper, and feature-local types.

Proposed canonical home:

- HTTP request/response contracts: backend Pydantic schemas and generated OpenAPI.
- Frontend HTTP types: `frontend/packages/intric-js/src/types/schema.d.ts`.
- Handwritten frontend code: ergonomic client wrapper and UI intent adapters only.
- SSE exception: a narrow AI Builder stream decoder owns event union types because OpenAPI currently models the stream as a string.

Merge/delete path:

- Replace `resources.d.ts` Flow runtime/authoring aliases with generated schema aliases or remove them.
- Type `flows.js` wrapper against generated operation request/response types or convert it to TS if that is the established client path.
- Delete manual AI Builder HTTP schema duplicates in `protocol.ts` after generated types cover them.
- Preserve typed SSE event decoder, chat UI message types, and UI intent types as explicit exceptions.

Acceptance criteria:

- No public Flow API shape exists only in `resources.d.ts` or component-local `Record<string, unknown>`.
- `flows.js` create-run request is type-compatible with generated `create_flow_run` request body.
- AI Builder SSE event types are documented as a manual stream adapter, not a competing HTTP schema.
- Generated-client update is part of any backend schema PR.

Tests required:

- Generated-client contract test for Flow run create/list/get/evidence/upload shapes.
- Type-level or compile test that frontend imports generated Flow schemas instead of manual resource aliases.
- Wrapper unit tests for request normalization/idempotency that use generated types.
- SSE decoder tests for status/text/question/plan/error/done events.

Risk/trade-off: generated schemas can be verbose for UI code. Keep narrow view models where they represent UI state, but derive them from generated types.

Human reviewability impact: backend schema changes produce visible generated diffs and failing frontend type checks instead of latent manual drift.

Confidence: high, with the SSE exception called out explicitly.

### 7. Frontend Flow State

Problem: frontend state ownership is fragmented across route pages, `FlowEditor`, panels, run dialog, evidence components, run table, and AI Builder Driver/Service mirrors.

Why it matters: frontend behavior becomes hard to reason about when source-of-truth state is copied between classes/components. New backend states or schema fields require repeated manual parsing and derived-value updates.

Evidence:

| Workflow | Evidence |
|---|---|
| Authoring | `FlowEditor` initializes resource editor and flow stores at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:27-120`; it also owns legacy cleanup at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:281-324`. |
| AI Builder Driver | Driver owns `FlowAIBuilderState` at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45-81`. |
| AI Builder Service mirror | Service declares mirrored `$state` fields at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:26-70` and copies driver state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:266-280`. |
| Evidence | Evidence component defines its own payload records at `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:45-80`. |
| Status/table | Table owns filters/counts/polling with local status literals at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:49-67`, `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:189-191`. |

Current owner: no single owner per workflow; `FlowEditor` is closest for authoring, `FlowAIBuilderService`/Driver compete for AI Builder, and components own run/evidence state.

Proposed canonical homes:

| Workflow | Canonical home |
|---|---|
| Flow authoring | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts` with command methods for step mutation, metadata/form schema, validation, publish readiness, and autosave. |
| AI Builder | `FlowAIBuilderService.svelte.ts` owns Svelte state; `FlowAIBuilderDriver.ts` becomes transport/SSE decoder and no longer owns durable UI state. |
| Run launch | New narrow `FlowRunLaunchSession` or equivalent module owns mutable launch state; `FlowRunDialog.svelte` becomes view/commands. |
| Evidence/progress | Generated evidence/run types plus feature view-model helpers own shape; components render. |

Merge/delete path:

- Move route-level and panel-level step mutations into typed `FlowEditor` commands.
- Delete AI Builder `#applyState` mirror after Driver is demoted or folded.
- Extract run launch contract loading/uploads/idempotency into a launch session module.
- Delete component-local evidence record types and status literal sets after generated types/status helper land.

Acceptance criteria:

- One object owns AI Builder session/messages/current plan/apply state.
- One authoring session object owns step ordering, reference remapping, validation, and save lifecycle.
- Components do not parse backend evidence/run payloads with `Record<string, unknown>` when generated types exist.
- Route `load` remains fetch-only and does not own domain orchestration.

Tests required:

- Frontend component journey: edit flow step through `FlowEditor` command and observe saved/validation state.
- AI Builder journey/unit: send message, receive stream events, plan visible, approve/apply state transitions through public service.
- Run launch component test: contract -> upload -> create run with `step_inputs`.
- Evidence component test using generated evidence fixture.

Risk/trade-off: picking Service as AI Builder state owner is an architectural decision. It matches Svelte reactivity and Phase 1a recommendations, but it requires carefully shrinking Driver without losing tested stream behavior.

Human reviewability impact: frontend reviewers can approve UI changes by workflow owner rather than tracing duplicated state across Driver, Service, route, and component.

Confidence: medium-high.

### 8. Legacy And Compatibility Paths

Problem: the codebase is pre-production but still contains compatibility shims, module aliases, star-import barrels, public request fallbacks, persisted-shape cleanups, and cycle-break shims.

Why it matters: compatibility paths create parallel owners and make reviewers ask whether old behavior is real product behavior. Some are safe deletion candidates; others guard public API or persisted data and need migration gates.

Evidence:

| Compatibility path | Evidence |
|---|---|
| Domain/service/repository shims | `backend/src/intric/flows/flow.py:1-37`, `backend/src/intric/flows/flow_service.py:1-5`, `backend/src/intric/flows/flow_run_service.py:1-22`, `backend/src/intric/flows/flow_dispatch.py:1-9`. |
| AI Builder model barrel | Star-import aggregation at `backend/src/intric/flows/ai_builder/ai_builder_models.py:1-5`. |
| Import-linter still names shim modules | `backend/.importlinter:21-45`. |
| Runtime file fallback | Legacy top-level file adapter at `backend/src/intric/flows/flow_run_step_inputs.py:104-128`; runtime fallback at `backend/src/intric/flows/runtime/step_input_resolution.py:401-402`. |
| Frontend persisted cleanup | Legacy mirrored input-template cleanup at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:281-324`. |

Current owner: scattered; Phase 1a Agent D owns inventory, but no implementation owner yet.

Proposed canonical home: concrete modules by layer. Compatibility inventory should become deletion PRDs/work items, not remain as runtime code owners.

Deletion classes:

| Class | Examples | Gate |
|---|---|---|
| Pure import compatibility | `flow_service.py`, repo shims, `ai_builder_models.py` | `rg` zero importers, update tests/startup imports/import-linter, delete. |
| Behavioral shim | `flow_run_service.py` logger rebinding, `flow_dispatch.py` module alias | Retarget tests and remove hidden behavior. |
| Public API compatibility | top-level `file_ids` | API/client/docs/usage/data gates. |
| Persisted data cleanup | legacy template config/form field/mirrored input templates | Backfill/prove zero rows, then delete cleanup/fallback tests. |
| Cycle-break shim | `flow_template_validation.py` | Add/import-linter boundary proof before deletion. |

Acceptance criteria:

- Every compatibility path has a verdict: delete now, migrate then delete, keep with invariant, or defer to named PRD.
- Pure shims have zero imports and are removed from `.importlinter`.
- Public/persisted compatibility paths have explicit data/API gates.
- Tests that only protect old import paths are rewritten or deleted.

Tests required:

- Startup/import-linter tests after shim deletion.
- Migration/backfill tests for persisted-shape fallbacks.
- API contract tests for public compatibility removal and error behavior.
- Search-based acceptance checks (`rg`) in PRD validation.

Risk/trade-off: deleting too aggressively can remove hidden cycle protection or public contract behavior. The delete-first rule still applies, but gates differ by compatibility class.

Human reviewability impact: reviewers see deliberate deletion with proof instead of compatibility comments and aliases that obscure the real owner.

Confidence: high.

## Acceptance Criteria Summary

- [ ] Status lifecycle projections exist and DB/API/frontend parity is tested.
- [ ] Published definition contract has one domain owner, first-class schema version, parser/writer tests, and corruption behavior.
- [ ] Flow access policy uses typed actions; audit actor identity is not duplicated; legacy principal `user_id` has a deletion gate.
- [ ] Evidence/provenance/redaction has versioned contracts and generated-client-safe public shapes.
- [ ] Runtime input/file mapping is step-scoped by default, with top-level `file_ids` deletion gates documented and tested.
- [ ] Frontend Flow API types come from generated schemas except explicit UI-intent/SSE adapters.
- [ ] Frontend authoring, AI Builder, run launch, evidence, and status state each have one owner.
- [ ] Compatibility paths have delete/migrate/keep verdicts and no unbounded "temporary" branches.

## Tests Required Summary

| Test layer | Required coverage |
|---|---|
| Domain/unit | Status lifecycle projections; published definition parser/writer; redaction/provenance parser; runtime step input normalization. |
| Data/migration | `flow_versions.schema_version`; legacy principal `user_id` removal; optional first-class `flow_run_step_inputs`; persisted-shape cleanup. |
| API contract | Flow run create/idempotency, run contract/upload, evidence/export, auth/action matrix, generated OpenAPI/client shape. |
| Runtime integration | Execute from versioned definition; stale/cancel/complete terminalization uses lifecycle projections; step-scoped file resolution. |
| Frontend component/journey | Flow editor commands; AI Builder service state; run launch; evidence rendering; status/progress presentation. |
| Static/parity | Enum-to-DB CHECK parity, generated type imports, zero shim imports, no manual Flow resource aliases. |

## Risk Register

| Risk | Mitigation | Confidence |
|---|---|---|
| New modules become shallow ceremony. | Only add modules that replace duplicated owners: `flow_definition.py`, `flow_status_lifecycle.py`, `flow_access_policy.py`. | Medium-high |
| Strict evidence/provenance typing rejects useful future forensic data. | Use versioned typed core plus controlled extension fields; require schema version and parser. | High |
| Deleting top-level `file_ids` breaks external consumers. | Gate on docs/client removal, zero queued/running legacy payloads, and usage telemetry/window. | Medium |
| Generated TS types are awkward for UI code. | Allow UI view models/intent adapters derived from generated types; forbid duplicate backend shapes. | High |
| Auth refactor changes permissions subtly. | Use an action matrix test before moving route helpers. | High |
| DB CHECK generation adds migration churn. | Start with parity tests; generate constraints as part of status-changing PRs. | Medium |

## Human Reviewability Impact

This pass turns scattered package-level findings into owner-level review rules. A future reviewer should be able to ask:

- Is this a status change? Start at `flow_status_lifecycle.py` and the status migration.
- Is this a definition-shape change? Start at `domain/flow_definition.py`.
- Is this a permission change? Start at `flow_access_policy.py`.
- Is this evidence/provenance? Start at the evidence cluster and versioned provenance model.
- Is this file mapping? Start at `flow_run_step_inputs.py` for submission and `step_input_resolution.py` for execution.
- Is this frontend API shape? Start at generated OpenAPI, not `resources.d.ts`.
- Is this frontend workflow state? Start at the workflow owner, not route/component mirrors.
- Is this compatibility? Start at the kill-list gate, not an unbounded fallback branch.

That makes diffs smaller in concept even when they are not smaller in LOC: the reviewer sees the owner, invariant, merge/delete path, and tests up front.

## Claude Peer Review

Required Claude peer loop was run with a 25-minute timeout.

| Iteration | Artifact | Verdict | Green light | Resulting Codex action |
|---|---|---|---|---|
| 1 | `.codex/artifacts/claude-peer-loop-phase-1b-agent-k-concept-invariants-direction-20260428T183855Z.md` | `changes_required` | `no` | Replaced broad owners with exact module proposals; split principal/access/audit; added published-definition owner, provenance versioning, top-level `file_ids` deletion gates, SSE exception, AI Builder state-owner decision, idempotency, and cycle-break shim nuance. |
| 2 | `.codex/artifacts/claude-peer-loop-phase-1b-agent-k-concept-invariants-verification-20260428T184742Z.md` | `green_light_with_minor_followups` | `yes` | No blocker changes required. Minor follow-ups deferred to Phase 2 PRDs: make the `file_ids` telemetry window concrete, confirm `flow_versions.schema_version` defaulting, confirm `FlowApiAction` granularity, and decide idempotency retention ownership. |

Codex verified Claude's blocking claims locally before revising:

- `flow_api_common.py` has string `required_access` and no typed action enum at `backend/src/intric/flows/api/flow_api_common.py:134`.
- `FlowVersions` has `definition_json` but no first-class schema-version column at `backend/src/intric/database/tables/flow_tables.py:231-243`.
- `FlowPrincipal` still writes legacy `user_id` and DB still stores it at `backend/src/intric/flows/principal.py:36-39`, `backend/src/intric/flows/principal.py:84-90`, and `backend/src/intric/database/tables/flow_tables.py:341-344`.
- Runtime still falls back to top-level `file_ids` for step 1 at `backend/src/intric/flows/runtime/step_input_resolution.py:401-402`.
- AI Builder Driver and Service both own mirrored state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45-81` and `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:26-70`.
- Attempt provenance remains JSONB with no version column at `backend/src/intric/database/tables/flow_tables.py:561-563`.
- No first-class `flow_run_step_inputs` DB table exists; current hit is only source module `backend/src/intric/flows/flow_run_step_inputs.py`.
- AI Builder SSE is generated as `text/event-stream: string` at `frontend/packages/intric-js/src/types/schema.d.ts:34460-34477`.
- `.importlinter` lists `flow_template_validation` as a source module but no dedicated cycle-boundary rule exists at `backend/.importlinter:21-45`.
- Audit actor mapping has at least two homes: `backend/src/intric/flows/principal.py:100-111` and `backend/src/intric/flows/api/flow_api_common.py:103-115`.

## Final 10-Dimension Scorecard

| Dimension | Score | Rationale |
|---|---:|---|
| Maintainability | 5 | Strong concept modules exist, but common changes still cross too many files. |
| Code Quality | 5 | Several owners are clear; broad JSON bags, manual TS types, and compatibility branches remain. |
| Clean Architecture | 5 | Domain/runtime/API/frontend boundaries exist, but HTTP helpers and services still own policy and projections. |
| Separation of Concerns | 4 | `flow_api_common.py`, `FlowRunService`, frontend Driver/Service, and evidence/debug/export clusters mix several reasons to change. |
| Single Source of Truth | 4 | Statuses, definition JSON, API/client types, audit actor mapping, and frontend state are duplicated. |
| Runtime Reliability | 5 | CAS/idempotency primitives exist, but lifecycle expansion and terminalization depend on scattered status semantics. |
| API Consumer DX | 5 | Happy path is usable; advanced file mapping/review/rerun/evidence typing need stronger contracts. |
| API Maintainer DX | 4 | Adding endpoints/statuses/schemas still requires manual router/schema/client/test coordination. |
| Human Readability | 6 | Names and modules often reveal intent, but large functions and compatibility shims obscure the entry point. |
| Human Reviewability | 4 | Reviewers must reconstruct ownership from scattered files; this document proposes the owner map needed to improve it. |

Overall score: 4/10, because the minimum dimension is 4. Refactor opportunistically before broad feature work, and require owner-defining PRDs before pause/review/rerun/file-mapping expansion.

## Non-Goals

- No source, test, migration, dependency, generated-client, or git changes in this pass.
- No new generic helper/service/interface recommendations.
- No endpoint-only design for pause/resume/review/rerun.
- No deletion of public or persisted compatibility paths without migration gates.

## Confidence

High for the existence of duplicated concepts and cited source locations. Medium-high for proposed canonical homes that require new narrow modules (`flow_definition.py`, `flow_status_lifecycle.py`, `flow_access_policy.py`) because implementation PRDs must still stage migrations and tests. Medium for frontend state sequencing because the Service-as-owner choice is clear enough for review but will require careful component rewiring.
