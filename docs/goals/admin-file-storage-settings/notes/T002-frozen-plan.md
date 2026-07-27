# T002 frozen plan

## Decision

`ready_for_worker`

Implement issue #569 PR 1 as two sequential slices:

1. T003 owns the complete backend and database behavior.
2. T004 starts only after T003 is green and owns generated contracts, the
   read-only tenant-admin experience, configuration cleanup, and documentation.

The existing `ENEO_SUPER_API_KEY` sysadmin boundary remains the only
deployment-wide mutation authority. Tenant administrators receive a sanitized
read projection and cannot mutate deployment policy. No new platform-admin
identity or browser use of the super key is permitted.

Claude Pass 1 findings about remote capture, post-commit failure, authority, and
tenant audit ownership are accepted. Its proposed removal of CAS, bounded
inventory, and exact invalid-seed failure is rejected because those conflict
with the explicit issue #569 tranche requirements.

## Frozen contract

### Policy and concurrency

One typed singleton row under `eneo.object_content` owns:

- singleton key constrained to `1`;
- `revision BIGINT >= 1`;
- `new_write_storage_kind` constrained to `postgres_inline|object_store`;
- positive `BIGINT` values for session file, session image, knowledge file,
  and transcription audio business limits;
- `updated_by_actor` constrained to `migration|sysadmin_super_api_key`;
- created and updated timestamps.

Full replacement PUT requires `expected_revision`. One conditional update
increments the revision; zero rows produces a typed 409 stale-revision error.
Readers see one complete committed revision through PostgreSQL MVCC. There is
no cache, history table, JSON policy, generic policy engine, per-tenant row, or
LISTEN/NOTIFY path.

### Authority and API

- Super-key-only GET/PUT live under the existing sysadmin surface.
- Tenant `Permission.ADMIN` receives a separate read-only sanitized projection.
- The browser never receives or submits `ENEO_SUPER_API_KEY`.
- 409 covers stale revision and permanently unavailable/incompatible target
  selection, 503 covers transient target outage or write verification failure,
  and 413 names a stable limit identifier plus the effective byte limit.

### Limits and ceilings

The API projects:

`use_case`, `storage_target|null`, `configured_bytes`,
`operator_ceiling_bytes|null`, `effective_bytes`, and
`constraining_source=admin_policy|operator_ceiling`.

- `session_file` uses the session-file policy and selected target.
- `session_image` uses the session-image policy and selected target.
- `session_audio` uses the transcription policy and selected target.
- `knowledge_file` uses the knowledge-file policy with no storage target or
  object-content ceiling.
- `knowledge_audio` uses the transcription policy with no storage target or
  object-content ceiling.

The inline operator ceiling applies only when the selected target is
`postgres_inline`. Effective is `min(configured, ceiling)` when applicable; a
tie reports `admin_policy`. Object-store multipart protocol limits are not
presented as business ceilings. Icon retains its fixed maximum and is also
clamped by the inline ceiling when inline.

The closed readers are `FileProtocol`, `TaskService`, `LimitService`, and
`AppAssembler`. Each admission reads the committed database policy; there is
no process-owned business-limit duplicate. Delete the restart-time
`required_inline_bytes` invariant.

### Eligible producers and failure contract

Eligible new-write producers are:

- `FileService.save_file()`, including exact, extracted/model-input content and
  derivative File rows;
- `FileService.save_image_from_bytes()`;
- `IconService.create_icon()`.

`save_transcription()`, InfoBlob/knowledge generation, Flow, existing content,
and moves remain out of scope.

Each aggregate pins one policy revision and target, verifies target readiness
before mutation, captures every content while retaining spools, commits
metadata plus durable intents and first references, then awaits
`store_and_verify()` for every remote content before returning success.
Target-aware capture uses inline chunking and the inline ceiling for
`postgres_inline`, and configured object-store spool/part sizes plus the
business/fixed limit for `object_store`.

If remote storage becomes unavailable or fails integrity verification,
compensating deletion removes the entire newly created File family or Icon
metadata and references in a new transaction, existing orphan cleanup owns
remote remnants, and the request returns a sanitized 503. A failed aggregate
must not appear in GET/list. Successful immediate reads return exact bytes.
There is no fallback, dual write, implicit move, or successful pending File.

### Migration seed and rollback

The migration descends from `202607241100`, creates revision 1 with
`postgres_inline`, and resolves the four legacy variables using the same
environment precedence as current Settings without importing mutable
application models.

Present positive values seed exactly. Explicit blank, non-integer, zero, or
negative values fail with the exact variable name and remediation; no clamp is
allowed. Absent values use evidenced fresh-install defaults of 10 MiB, 10 MiB,
10 MiB, and 200 MiB. Subsequent environment changes and restarts never
overwrite the row. Once the migration and consumers are green, remove all four
runtime Settings fields and active deployment configuration.

Before application rollback, operators export the four current values and
target, restore the legacy environment values, then start the old application
or downgrade. Downgrade drops only the policy table and never moves or deletes
content.

### Audit, capability, and inventory

The tenant audit table must not receive this deployment event. A successful PUT
persists `sysadmin_super_api_key` attribution and emits one structured
operational log with the event name, old/new non-secret policy values, old/new
revision, and actor `{type: sysadmin, via: eneo_super_api_key}`. It must never
log the key, endpoints, buckets, object keys, credentials, deployment IDs, or
raw failures. Durable global audit history is explicitly deferred.

Capability rows expose only target, configured, selectable, and a stable
readiness code. Object store is selectable only on verified `READY`. Inventory
reuses the existing grouped owner and exposes only target, lifecycle state,
count, and bytes, bounded to `StorageKind × ContentState` (at most 12 rows).
No timestamps, identifiers, infrastructure details, or raw blockers are
returned.

## Canonical ownership

- Process `Settings` limits -> singleton object-content deployment policy.
- Scattered limit derivation -> one typed policy reader/projection injected
  into the closed consumers.
- Inline-only capture -> target-aware `ObjectContentService` capture.
- Hard-coded File/Icon placement -> policy-pinned producer lifecycle.
- Capability -> remains `ObjectContentRuntime`.
- Inventory aggregation -> remains the reconciliation repository.
- Deployment mutation -> existing sysadmin/super-key adapter.
- Tenant UI state -> generated read contract and one admin page.

## Red-first proof

- CAS rejects a stale writer while concurrent readers observe complete old or
  new revisions.
- Migration preserves valid legacy values exactly, uses fresh-install defaults
  only when absent, rejects invalid values, and survives
  upgrade/downgrade/re-upgrade without overwrite or extra Alembic heads.
- Independent API-style and worker-style service instances observe updates
  without restart.
- Every projected use case accepts maximum and rejects maximum + 1, including
  both transcription branches and operator-ceiling constraints.
- Target-aware capture works above the multipart threshold.
- Remote unavailable/integrity failure leaves no File family or Icon metadata.
- Inline and compatible object store produce byte-identical immediate reads.
- Authorization, sanitized failures/facts, 12-row inventory bound, constant
  query count/query plan, and absence of moves/fallback/dual write are covered.

## Deferred

Platform-admin identities, editable browser mutation, durable system audit
history, issue #569 PR 2 moves, cleanup/migration UI, per-tenant
policy/routing/buckets/dedupe, transcription placement, InfoBlob/knowledge
generation, Flow, third backends/provider registries, issues #571 and #586.
