# Flow Permission And Data Contracts

## TL;DR

1. `backend/src/intric/flows/flow_access_policy.py` owns Flow and Flow AI Builder action-to-permission mapping.
2. `backend/src/intric/flows/principal.py` owns user/service-key identity and legacy `flow_runs.user_id` projection.
3. Published flow definitions remain JSONB, but `backend/src/intric/flows/published_definition.py` owns the schema-versioned envelope.
4. Flow idempotency replay is retained for the lifetime of the matching `flow_runs` row; there is no TTL or sweep today.
5. Runtime facts that need queryability, lifecycle, retry, retention, review, or audit ownership must become relational rows before new features rely on them.

## Permission Mapping

| Action | Current permission requirement | Service-key behavior | `flow.edit` precondition | Notes |
|---|---|---|---|---|
| `view` | `FLOWS_VIEW` | Allowed only when the route explicitly allows service-key principals. | No | `FLOWS` remains a legacy alias for shipped view behavior. |
| `run` | `FLOWS_RUN` | Allowed only when the route explicitly allows service-key principals. | No | Used by published runtime routes. |
| `edit` | `FLOWS_MANAGE` | Denied. | Yes | Replaces route-local `"manage"` strings. |
| `trace_view` | `FLOWS_VIEW` and `FLOWS_TRACE` | Denied. | No | Keeps the existing view-plus-trace requirement. |
| AI Builder session/create/list/read/message/models/plans/cancel/approve/apply/revise | `FLOWS_MANAGE` and `FLOWS_AI_BUILDER` | Denied. | Yes | Creator ownership is declared per endpoint in the AI Builder route helper. |
| `review` | No shipped permission grant. | Denied. | Not yet applicable. | Future action; legacy aliases must not grant it implicitly. |
| `resume` | No shipped permission grant. | Denied. | Not yet applicable. | Future action; legacy aliases must not grant it implicitly. |
| `rerun` | No shipped permission grant. | Denied. | Not yet applicable. | Future action; legacy aliases must not grant it implicitly. |
| `audit_view` | No shipped permission grant. | Denied. | Not yet applicable. | Future action; legacy aliases must not grant it implicitly. |

Legacy `FLOWS`, `FLOWS_MANAGE`, and `FLOWS_RUN` are retained because tenant role assignments may already store them. They must not be deleted or expanded silently. New Flow actions require an explicit policy row, tests, and a migration note before any route uses them.

## Principal Identity

`FlowPrincipal` is the canonical identity owner for Flow runtime work:

- user principals set `principal_type='user'`, `principal_user_id`, and legacy `user_id`
- service-key principals set `principal_type='service_key'`, `principal_api_key_id`, and `user_id=None`
- audit actor fields come from `FlowPrincipal.audit_actor_fields()`
- file ownership fields come from `FlowPrincipal.file_owner_fields()`

`flow_runs.user_id` remains a compatibility projection for historical user-principal rows. New read filters must use `principal_type` plus `principal_user_id` or `principal_api_key_id`, not `flow_runs.user_id`.

## Published Definition JSONB

`FlowVersions.definition_json` remains the persisted snapshot for published flow definitions. The owned envelope has:

- `schema_version`
- `flow_id`
- `name`
- `description`
- `metadata_json`
- `steps`

`published_definition.py` owns the envelope parser/writer and checksum. Step-body validation stays in `runtime/step_definition_parser.py` so input source, output type, transcribe-only, and chain-order rules do not fork.

Named corruption codes:

- `flow_definition_schema_version_missing`
- `flow_definition_schema_version_unsupported`
- `flow_definition_flow_id_invalid`
- `flow_definition_steps_invalid`

Unsupported or corrupt definitions fail before runtime execution. This is intentionally stricter than treating malformed snapshots as empty flows.

## Idempotency Retention

Flow run idempotency is row-lifetime based today:

- a matching retained `flow_runs` row with the same tenant, flow, principal, idempotency key, and request fingerprint replays the existing run
- the same key with a different fingerprint returns `flow_run_idempotency_conflict`
- if the row is deleted by a future retention policy or manual operation, the same key is treated as a new create request after normal validation
- clients must keep the returned run id as the durable polling handle

There is no production TTL column, expiry timestamp, or sweep job for Flow idempotency in this batch. Adding one is a public-contract and data-retention change.

## JSONB Extraction Gate

Keep JSONB when the payload is a heterogeneous snapshot, arbitrary model output, or run-local envelope that does not need independent lifecycle/query behavior.

Create relational rows when the fact needs any of these:

- cross-run query/filter/index support
- row-level authorization
- retention ownership
- retry/idempotency ownership
- lifecycle transitions
- review/pause/resume state
- audit/outbox durability
- operator debugging without JSON scanning

## Required Future Runtime Tables

These are schema requirements before implementation starts in the later runtime batches; this document is not an Alembic migration.

| Table | Ownership | Minimum keys and constraints | Why relational |
|---|---|---|---|
| `flow_run_step_input_files` | Attempt-scoped input file mapping | `id`, `tenant_id`, `flow_id`, `flow_run_id`, `step_id`, `file_id`, `attempt_id`; foreign keys to run/flow/file/attempt; unique `(flow_run_id, attempt_id, step_id, file_id)`; tenant/flow consistency constraints. | File associations must be queryable by run, step, file, and attempt, and cannot point across tenant/flow boundaries. |
| `flow_run_step_result_files` | Step output artifact projection | `id`, `tenant_id`, `flow_id`, `flow_run_id`, `step_result_id`, `step_id`, `file_id`, artifact role; foreign keys to run/result/file; unique `(step_result_id, file_id, artifact_role)`. | Artifact retrieval, retention, evidence export, and rerun invalidation should not scan output JSON. |
| `flow_run_rerun_operations` | Rerun command/idempotency owner | `id`, `tenant_id`, `flow_id`, `flow_run_id`, requested start step, invalidated step ids snapshot, status, actor principal fields, idempotency key/fingerprint; unique active idempotency key per principal/run. | Rerun is a lifecycle operation with retry, invalidation, and audit semantics. |
| `flow_run_review_checkpoints` | Human review pause/resume owner | `id`, `tenant_id`, `flow_id`, `flow_run_id`, `step_id`, checkpoint status, pending output snapshot, edited output snapshot, reviewer principal fields, resume token/version. | Review checkpoints need compare-and-set resume behavior and must survive worker exits. |
| `flow_run_audit_outbox` | Runtime audit delivery owner | `id`, `tenant_id`, `flow_id`, `flow_run_id`, action, entity, actor principal fields, payload, delivery status, retry count, next attempt. | Terminalization and important runtime transitions need durable audit retry/alert behavior. |

New tables require an ADR or this document's successor to specify query patterns, retention behavior, transaction boundary, migration/backfill plan, and rollback path before Alembic implementation.
