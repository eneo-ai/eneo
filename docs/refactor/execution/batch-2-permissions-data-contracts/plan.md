# Batch 2 - Permissions And Data Contracts Plan

## Scope

Implement PRD-002 for Flow / Flow AI Builder permission and data-contract foundations.

Batch 2 starts from these committed checkpoints:

- Batch 0 source/test checkpoint: `d6a9365e477b83651d94566f58a9a7e13d0b9363`
- Post-Batch-0 governance/docs checkpoints:
  - `88cfc4016aa4c5b69506bee5f8b887a1f70a47c1`
  - `8f21fd4f9ca745df8bd0761923350e2f304640ed`
  - `ad472c61bf34b3a5ced13198e141c78c693e5bc0`
- Batch 1 source/test/docs checkpoint: `61c17ed712e245eb25c2f124f334c6c9cbc42413`

Batch 2 is not a generated-client/package rename batch. Generated-client/package naming remains deferred to Batch 5. The Python backend namespace remains `intric.*`; do not create `eneo.*` alias modules or dual import namespaces.

## Current Source-Of-Truth Owners

| Concept | Current source owner | Current false owner / drift | Batch 2 direction |
|---|---|---|---|
| Flow tenant permission checks | `backend/src/intric/flows/flow_permissions.py:10-103` owns helper functions over `Permission.FLOWS_*`. | The helpers expose capability-specific functions but no typed action vocabulary for route call sites. | Add one Flow policy module that owns typed actions and permission mapping; keep `flow_permissions.py` as a temporary adapter around the policy during migration. |
| Flow route action selection | `backend/src/intric/flows/api/flow_api_common.py:129-285` owns route access resolution and scope enforcement. | `required_access: str` plus string branches at `flow_api_common.py:179-193`; route call sites pass `"view"`, `"run"`, and `"manage"`. | Replace free-form strings with typed `FlowApiAction` at route helper boundaries and update Flow route call sites. |
| API-key scope extraction | `intric.authentication.auth_dependencies.get_scope_filter` owns `Request.state.api_key_scope_*` extraction at `backend/src/intric/authentication/auth_dependencies.py:295-329`. | AI Builder router duplicates raw `Request.state` reads at `backend/src/intric/flows/ai_builder/ai_builder_router.py:180-210` and honors `scope_enforcement_enabled` as a production switch. | Route AI Builder scope checks through the Flow policy/scope helper. No Flow or AI Builder router should read `Request.state.api_key_scope_*` directly after this batch. |
| AI Builder permissions | `ai_builder_router.py` checks `ensure_can_use_flow_ai_builder` and local session-creator helpers. | AI Builder actions do not declare typed action requirements or creator-ownership requirements in one place. | Add typed policy actions for every AI Builder endpoint and one route helper that declares action, space scope, filter mode, and creator-ownership requirements. |
| Principal identity | `backend/src/intric/flows/principal.py:18-119` owns `FlowPrincipal`, legacy `user_id` projection, service-key identity, file ownership fields, and audit actor fields. | `flow_runs.user_id` remains alongside `principal_type`, `principal_user_id`, and `principal_api_key_id`. | Treat `FlowPrincipal` as canonical. Do not delete `flow_runs.user_id`; document historical/legacy migration status and keep read/write compatibility. |
| Published definition JSON | `FlowVersions.definition_json` is persisted JSONB at `backend/src/intric/database/tables/flow_tables.py:231-243`; `FlowService` writes schema version and payload at `backend/src/intric/flows/application/flow_service.py:47` and `686-780`; runtime step parser reads raw dicts at `backend/src/intric/flows/runtime/step_definition_parser.py:33-187`. | Version behavior is split between the writer and raw runtime parsing. Some readers call `definition_json.get(...)` directly. | Add a published-definition contract owner with schema version, parser, writer, checksum helper, and named corruption errors. Route existing writer and runtime readers through it where in scope. |
| Idempotency retention | `FlowRunService.create_run` validates idempotency keys and fingerprints at `backend/src/intric/flows/application/flow_run_service.py:314-451`; `flow_runs` unique indexes retain replay rows at `backend/src/intric/database/tables/flow_tables.py:350-440`. | Retention semantics are row-lifetime based but not owned as a data contract beyond Batch 1 API docs. | Add explicit read-side semantics tests and durable docs: replay works only while the matching retained `flow_runs` row exists; after expiry/deletion, clients must use run polling by run id. No TTL migration in this batch. |
| JSONB extraction policy | `docs/refactor/architecture-decision-backlog.md` has high-level decisions for runtime file mapping, extraction, rerun, review, and audit/outbox. | The required table schemas/constraints are not yet written before later runtime implementation batches. | Add a durable JSONB extraction/data-contract doc or ADR-style section that defines table candidates, constraints, and ownership gates before migrations. Do not add Alembic migrations in this batch unless Claude finds the PRD requires it now. |

## Planned Typed Actions And Policy Seams

`backend/src/intric/flows/flow_access_policy.py` will be the only Flow module that calls `has_permission(...)` for `Permission.FLOWS_*`. It will expose typed actions for existing route behavior and future denied-by-default actions:

- current Flow route actions: `view`, `run`, `edit`, `trace_view`
- current AI Builder route actions: `builder_session_create`, `builder_session_list`, `builder_message_send`, `builder_session_read`, `builder_attachment_detach`, `builder_models_list`, `builder_plan_read`, `builder_plan_list`, `builder_session_cancel`, `builder_plan_approve`, `builder_plan_apply`, `builder_plan_revise`
- future denied-by-default actions: `review`, `resume`, `rerun`, `audit_view`

Policy helpers will take `FlowPrincipal` where principal identity matters. All `active_api_key.ownership` decoding remains in `FlowPrincipal.from_user`; `flow_api_common.py`, `flow_permissions.py`, `flow_router_common.py`, and AI Builder router code must not duplicate that decode.

AI Builder endpoints should call one helper shape rather than manually chaining scope, tenant permission, and creator checks at each route:

```python
authorize_ai_builder_request(
    request=request,
    container=container,
    action=FlowApiAction.BUILDER_PLAN_APPLY,
    space_id=session.space_id,
    session=session,
    require_creator=True,
    filter_mode=None,
)
```

List endpoints that intentionally filter instead of deny must declare a filter mode explicitly. The first Batch 2 target is AI Builder session listing; it should filter to the scoped/permitted spaces without per-row denial audit noise.

Published definition ownership is intentionally split:

- `published_definition.py` owns the envelope: `schema_version`, `flow_id`, name, description, metadata, sorted steps, JSONB round-trip, and checksum.
- `runtime/step_definition_parser.py` keeps step-body validation: input/output source, input/output type, output mode, transcribe-only rules, contiguous step order, and chain rules.
- `published_definition.py` delegates runtime step parsing to `parse_runtime_steps` instead of duplicating step validation.

Named published-definition corruption codes to pin:

- `flow_definition_schema_version_missing`
- `flow_definition_schema_version_unsupported`
- `flow_definition_steps_invalid`

## Behavior Pins To Add Or Rewrite BEFORE Destructive Cleanup

- [ ] Add `backend/tests/unittests/flows/test_flow_access_policy.py` before replacing route string actions:
  - user principals with `FLOWS_VIEW`, `FLOWS_RUN`, `FLOWS_MANAGE`, `FLOWS_AI_BUILDER`, and `FLOWS_TRACE` are accepted/rejected by typed action, not helper identity
  - service-key principals fail closed for user-only actions with `flow_service_key_principal_not_supported`
  - service-key principals are allowed only for explicitly declared published runtime view/run actions used by Batch 1 API contracts
  - permission migration matrix documents and tests legacy `FLOWS` and granular aliases, and records whether each AI Builder action requires `flow.edit` as a precondition
  - `FLOWS` may keep current legacy grants for shipped actions but must not silently grant future `review`, `resume`, `rerun`, or `audit_view`
  - `FLOWS_MANAGE` and `FLOWS_RUN` must not grant `review`, `resume`, `rerun`, or `audit_view`
- [ ] Update `backend/tests/unittests/flows/test_flow_permissions.py` so existing helper tests assert the adapter behavior around the typed policy, not a second permission source of truth.
- [ ] Add or update AI Builder router tests before replacing raw scope helpers:
  - create session enforces space-scoped API key access through the policy helper
  - list sessions declares filter mode and filters to scoped space without raw route state reads
  - session routes still enforce creator ownership where required
  - no test depends on `scope_enforcement_enabled` as a production bypass
  - all AI Builder endpoints use a single helper that takes a typed action rather than manually chaining `_require_ai_builder_scope`, `_ensure_flow_edit_permission`, and `_ensure_session_creator`
- [ ] Add source guard tests before cleanup:
  - Flow modules other than `flow_access_policy.py` must not call `has_permission(...)` for `Permission.FLOWS_*`
  - modules other than `principal.py` must not define service-key helper functions or duplicate `getattr(key, "ownership", "user")`
  - Flow and AI Builder router modules must not read `Request.state.api_key_scope_type`, `api_key_scope_id`, or `scope_enforcement_enabled`
  - `scope_enforcement_enabled` must not appear under `backend/src/intric/flows/**` after this batch
  - production Flow repository/service read filters must not use `FlowRuns.user_id` directly outside the documented `FlowPrincipal.from_run` legacy fallback; writes/projections can keep `user_id` until the migration decision
- [ ] Add `backend/tests/unittests/flows/test_published_definition_contract.py` before moving JSONB parsing/writing:
  - writer includes the current schema version, flow identity, metadata, and sorted steps
  - parser round-trips a valid published definition and returns parsed runtime steps
  - parser rejects missing, non-integer, or unsupported schema versions with `flow_definition_schema_version_missing` or `flow_definition_schema_version_unsupported`
  - parser rejects missing or invalid `steps` with `flow_definition_steps_invalid` while preserving the existing runtime validation semantics
  - checksum uses the same stable hash as the existing published version persistence
- [ ] Add or extend idempotency tests in `backend/tests/unittests/flows/test_flow_run_service.py`:
  - matching key and payload replays only when the repository returns a retained row
  - no retained row means the service creates a new run after normal validation and concurrency checks
  - different payload still returns `flow_run_idempotency_conflict`
  - tests make row-lifetime retention explicit without adding TTL columns
- [ ] Add a cross-principal idempotency isolation test in `backend/tests/integration/flows/test_flow_run_repository.py`, proving user-keyed and service-key-keyed idempotency keys with the same string value on the same tenant/flow do not collide against the real repository/database partial unique indexes.
- [ ] Add docs pins before migrations:
  - JSONB extraction policy names which facts require relational rows and why
  - attempt-scoped input file rows, step result file rows, rerun operations, review checkpoints, and audit/outbox rows have proposed schemas and constraints
  - permission migration mapping documents legacy aliases and future action non-grants
  - no TTL or retention sweep exists for Flow idempotency today; rows are retained until manual deletion or a future explicit retention policy

## Files To Change

### Tier A - Source-Only / Safe To Replace After Pins

Expected source changes:

- `backend/src/intric/flows/flow_access_policy.py`
  - new canonical policy module with `FlowApiAction`, action metadata, service-key support rules, route filter-mode vocabulary, and permission mapping
  - owns canonical tenant-role denial shape for Flow policy decisions
  - only Flow module allowed to call `has_permission(...)` for `Permission.FLOWS_*`
- `backend/src/intric/flows/flow_permissions.py`
  - delegates to typed policy helpers during migration
  - keep public helper names until all callers are moved; do not duplicate permission mapping here
  - remove local service-key ownership decoding and use `FlowPrincipal.from_user`
- `backend/src/intric/flows/api/flow_api_common.py`
  - replace `required_access: str` with typed action parameters
  - route service-key allowlist decisions through policy metadata
  - keep route-scope and actor-space behavior here as HTTP adapter behavior
  - remove local `is_service_key_principal`; callers should use policy/`FlowPrincipal`
- `backend/src/intric/flows/api/flow_router_common.py`
  - typed wrapper signatures for route modules
  - remove the `is_service_key_principal` re-export after updating consumers
  - keep the router audit actor helper only as an HTTP adapter that delegates to `FlowPrincipal.audit_actor_fields`
- Flow route modules under `backend/src/intric/flows/api/`
  - replace `"view"`, `"run"`, and `"manage"` call-site strings with `FlowApiAction` values
  - do not change paths, operation IDs, request models, response models, pagination shape, or error shape unless the plan is revised
- `backend/src/intric/flows/ai_builder/ai_builder_router.py`
  - remove raw API-key scope reads from router helpers
  - route builder use, scope enforcement, scoped list filtering, and creator-session checks through policy-owned helpers or policy-owned value objects
  - delete `_ROUTER_TEST_COMPAT_HELPERS` if zero-consumer proof confirms it is unused
- `backend/src/intric/flows/published_definition.py`
  - new canonical owner for published definition schema version, parsing, writer assembly, and checksum
  - keep arbitrary user/model output JSON out of this module
  - delegate step-body validation to `runtime.step_definition_parser.parse_runtime_steps`
- `backend/src/intric/flows/application/flow_service.py`
  - use published-definition writer/checksum owner when creating `FlowVersions`
- `backend/src/intric/flows/application/flow_run_service.py`
  - parse published definitions through the new contract owner where it currently handles runtime file input validation
  - keep existing idempotency source names unless implementation shows a real readability problem; tests and docs own the retention semantics in this batch
- `backend/src/intric/flows/runtime/executor.py`, `backend/src/intric/flows/flow_file_upload_service.py`, and `backend/src/intric/flows/api/flow_run_steps_router.py`
  - route definition parsing through the published-definition owner where direct raw reads are in scope

Expected test/doc changes:

- `backend/tests/unittests/flows/test_flow_access_policy.py`
- `backend/tests/unittests/flows/test_flow_permissions.py`
- `backend/tests/unittests/flows/test_flow_router.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py`
- `backend/tests/unittests/flows/test_published_definition_contract.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/integration/flows/test_flow_run_repository.py`
- `docs/refactor/execution/batch-2-permissions-data-contracts/plan.md`
- `docs/refactor/execution/batch-2-permissions-data-contracts/journal.md`
- later in the loop: `retrospective-1.md` and `claude-reconciliation-1.md`
- one durable docs artifact for Batch 2 decisions, expected to be either:
  - `docs/refactor/flow-permission-and-data-contracts.md`, or
  - a narrowly named ADR-style doc under `docs/refactor/`

### Tier B - Persisted / Public Surfaces Not To Delete In Batch 2

| Surface | Owner | Why not deleted in Batch 2 | Later owner |
|---|---|---|---|
| `flow_runs.user_id` | `FlowPrincipal` plus flow run repository/table mappings | Persisted legacy field and historical query path. PRD-002 explicitly says not to delete without migration proof. | Dedicated migration or historical-only decision after zero-import/query proof. |
| `flow_versions.definition_json` | `FlowVersions` and new published-definition contract | Persisted published definitions remain JSONB. Batch 2 adds parser/writer ownership; it does not normalize definitions into tables. | Future schema-version migration only if contract owner proves it is needed. |
| Top-level run request `file_ids` | `FlowRunCreateRequest`, `FlowRunService.create_run`, runtime input resolution, JS wrapper | Public request surface and persisted input snapshot pinned in Batch 1. | Batch 4 per-step file mapping. |
| `template_file_id` in template output configs | Flow template compatibility code and published definitions | Historical published definitions may still contain it; parser must keep reading it. | Batch 4 or later persisted-reader cleanup after proof. |
| Old form field type values | Flow metadata/form-schema readers | Persisted metadata and client-visible schemas can still contain old values. | Batch 4/10 schema-version cleanup. |
| HTTP config converters / authored config readers | HTTP authored config modules and FlowService secret merge | Persisted authored configs may contain old values; not part of permission/data policy cleanup. | Dedicated HTTP config migration/backlog item. |
| Historical evidence/export keys | Evidence/export modules and Batch 1 OpenAPI/API pins | Audit/support history must remain readable/exportable. | Evidence schema-version migration, not Batch 2. |
| Existing role permission aliases | `backend/src/intric/roles/permissions.py` | `FLOWS` and granular aliases may exist in tenant role assignments. Batch 2 documents/tests migration behavior; it does not delete role values. | Role migration/backfill after explicit approval. |
| `scope_enforcement_enabled` outside Flow routes | Authentication/test infrastructure | Batch 2 should remove router reliance in Flow/AI Builder, not rewrite global auth infrastructure. | Auth infrastructure cleanup only if a separate owner approves it. |
| Generated OpenAPI/client package naming | Backend route schemas and `frontend/packages/intric-js` | Batch 2 internal typed actions should not change public OpenAPI. Package naming belongs to Batch 5. | Batch 5 generated-client/package naming decision. |
| `_resolve_litellm_params` test seam | `ai_builder_router.py` and AI Builder service | It is in the router being touched but is not permission, scope, JSONB, or idempotency behavior. | AI Builder split cleanup in Batch 6. |

No source-only compatibility shim should be restored unless a real external consumer is proven.

## Public Contract / Generated Client Impact

- Replacing route helper strings with `FlowApiAction` is an internal backend refactor and should not alter OpenAPI.
- Any route path, operation ID, request model, response model, pagination shape, error shape, or status-code change is a public-contract change and is out of scope unless Claude review forces a plan revision.
- Permission denials must keep the canonical error shape and existing error codes unless a deliberate API change is documented before implementation.
- Published-definition parser errors are internal runtime/application errors over persisted data. They should use named `BadRequestException` codes for corrupt or unsupported persisted definitions, but should not add a public API schema field.
- Generated-client/package naming is deferred to Batch 5.
- No TTL or retention sweep exists for Flow idempotency today. The current public behavior is row-lifetime replay: if the retained `flow_runs` row exists for the same tenant, flow, principal, key, and fingerprint, creation replays; if the row no longer exists, the same key is treated as a new create request after normal validation.

## Claude Plan Review Reconciliation

Claude iteration 1 returned `GREEN_LIGHT: no`. The following plan changes reconcile the accepted findings before implementation:

- Accepted: add source guards so `flow_access_policy.py` is the only Flow module that maps `Permission.FLOWS_*` via `has_permission(...)`.
- Accepted: collapse service-key ownership decoding into `FlowPrincipal.from_user`; remove duplicate `is_service_key_principal` helpers and re-exports in Flow API modules.
- Accepted: enumerate AI Builder typed actions and require one route helper signature for action, scope, filter mode, and creator-ownership checks.
- Accepted: strengthen the `scope_enforcement_enabled` pin so Flow production routes no longer rely on it as a bypass.
- Accepted: make permission migration mapping a parametrized behavior pin, including explicit non-grants for future `review`, `resume`, `rerun`, and `audit_view`.
- Accepted: define the boundary between `published_definition.py` envelope parsing and `step_definition_parser.py` step-body parsing, with named corruption error codes.
- Accepted: state that no idempotency TTL/sweep exists today and add cross-principal idempotency isolation coverage.
- Accepted: include the `flow_router_common.py` pass-through service-key re-export and AI Builder `_ROUTER_TEST_COMPAT_HELPERS` tuple as Tier A deletion candidates after consumer proof.
- Deferred: `_resolve_litellm_params` is a test seam in the AI Builder router but belongs to Batch 6's AI Builder split rather than Batch 2 permission/data contracts.

## Validation Commands

Implementation order row for Batch 2 says:

```text
Permission matrix tests; parser round-trip tests; pyright
```

Operationalized commands for this iteration:

```bash
git diff --check -- \
  backend/src/intric/flows/flow_access_policy.py \
  backend/src/intric/flows/flow_permissions.py \
  backend/src/intric/flows/api/flow_api_common.py \
  backend/src/intric/flows/api/flow_router_common.py \
  backend/src/intric/flows/api \
  backend/src/intric/flows/ai_builder/ai_builder_router.py \
  backend/src/intric/flows/published_definition.py \
  backend/src/intric/flows/application/flow_service.py \
  backend/src/intric/flows/application/flow_run_service.py \
  backend/src/intric/flows/runtime/executor.py \
  backend/src/intric/flows/flow_file_upload_service.py \
  backend/tests/unittests/flows/test_flow_access_policy.py \
  backend/tests/unittests/flows/test_flow_permissions.py \
  backend/tests/unittests/flows/test_flow_router.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  backend/tests/unittests/flows/test_published_definition_contract.py \
  backend/tests/unittests/flows/test_flow_run_service.py \
  backend/tests/integration/flows/test_flow_run_repository.py \
  docs/refactor/execution/batch-2-permissions-data-contracts
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest \
  tests/unittests/flows/test_flow_access_policy.py \
  tests/unittests/flows/test_flow_permissions.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_run_repository.py \
  -q
```

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_access_policy.py \
  tests/unittests/flows/test_flow_permissions.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_run_repository.py \
  -q
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright \
  src/intric/flows/flow_access_policy.py \
  src/intric/flows/flow_permissions.py \
  src/intric/flows/api/flow_api_common.py \
  src/intric/flows/api/flow_router_common.py \
  src/intric/flows/ai_builder/ai_builder_router.py \
  src/intric/flows/published_definition.py \
  src/intric/flows/application/flow_service.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/flow_file_upload_service.py \
  tests/unittests/flows/test_flow_access_policy.py \
  tests/unittests/flows/test_flow_permissions.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_run_repository.py
```

```bash
cd backend && uv run pyright \
  src/intric/flows/flow_access_policy.py \
  src/intric/flows/flow_permissions.py \
  src/intric/flows/api/flow_api_common.py \
  src/intric/flows/api/flow_router_common.py \
  src/intric/flows/ai_builder/ai_builder_router.py \
  src/intric/flows/published_definition.py \
  src/intric/flows/application/flow_service.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/flow_file_upload_service.py \
  tests/unittests/flows/test_flow_access_policy.py \
  tests/unittests/flows/test_flow_permissions.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_run_repository.py
```

```bash
rg -n "required_access=\\\"(view|run|manage)\\\"|required_access: str|Request\\.state\\.api_key_scope_|api_key_scope_type|api_key_scope_id|scope_enforcement_enabled|has_permission\\(.*Permission\\.FLOWS|getattr\\(key, \\\"ownership\\\", \\\"user\\\"\\)|def .*is_service_key" \
  backend/src/intric/flows
```

Expected after implementation: no string route access call sites remain; Flow/AI Builder router modules do not read raw API-key scope state; only `flow_access_policy.py` maps Flow role permissions; only `principal.py` decodes service-key ownership. If Docker execution is blocked by the host approval policy, classify it as an environment issue and run the local fallback commands.

## Acceptance Criteria (Verbatim From PRD-002)

- [ ] One flow policy module owns typed actions.
- [ ] No flow router reads `Request.state.api_key_scope_*` directly.
- [ ] Published definition parser/writer owns version behavior.
- [ ] Idempotency retention has read-side semantics for retries after expiry.
- [ ] JSONB extraction ADR exists before any non-lifecycle run-local artifact/input table is created.
- [ ] Attempt-scoped file input rows, step output file rows, rerun operation rows, review checkpoint rows, and audit/outbox rows have schemas and constraints before implementation starts.
- [ ] Permission migration mapping is documented and tested.

## Out Of Scope For This Batch

- Do not start Batch 3.
- Do not add step rerun or human review endpoints.
- Do not normalize every JSONB field into tables.
- Do not add Alembic migrations unless the plan is revised after Claude review.
- Do not delete `flow_runs.user_id`.
- Do not delete permission aliases.
- Do not remove top-level run request `file_ids`.
- Do not remove `template_file_id`, old form field type readers, HTTP config converters, or historical evidence keys.
- Do not change OpenAPI route paths, operation IDs, request models, response models, pagination shape, or error shape unless explicitly documented as a public-contract change.
- Do not migrate generated frontend types or `frontend/packages/intric-js` package naming; Batch 5 owns that.
- Do not rename existing `intric.*` Python imports/modules/packages to `eneo.*`.
- Do not create `eneo.*` Python aliases or dual import namespaces.
- Do not modify unrelated dirty files:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- Do not push, open a PR, stage, or commit without explicit user approval.
