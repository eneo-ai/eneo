# T001 — Source and Ownership Map

## Receipt

`ready_for_judge`

The Scout mapped issue #569 PR 1 at pinned base
`2746098cc008f7e9b95eae775ae4501a11cdb5c3`. The PM independently re-ran the
critical searches and accepted the findings below, with one correction: this
worktree does contain the tracked root `AGENTS.md`; the five
`docs/engineering/*` files it references are absent from live `origin/develop`,
so uncommitted files from another checkout are not treated as authority.

## Canonical Ownership

| Concern | Current owner and evidence | Proposed PR 1 owner |
|---|---|---|
| Business upload limits | Process `Settings` fields in `backend/src/eneo/main/config.py:357-361`, read directly by `FileProtocol`, `TaskService`, `LimitService`, and `AppAssembler` | One typed deployment policy row under `eneo.object_content`, read transactionally from PostgreSQL |
| Operator inline ceiling | `ObjectContentCoreSettings.inline_maximum_bytes` in `backend/src/eneo/object_content/configuration.py:19-56` | Keep deployment-owned in `ObjectContentRuntime`/`ObjectContentService` |
| Placement capability | Runtime composition and readiness in `backend/src/eneo/object_content/runtime.py:61-150,170-248` | Keep runtime-owned; expose only sanitized capability facts |
| New File/Icon placement | Hard-coded `POSTGRES_INLINE` in `backend/src/eneo/files/file_service.py:141-194,349-370` and `backend/src/eneo/icons/icon_service.py:94-128` | Target-aware lifecycle behind `ObjectContentService`; producers must not infer capability |
| Inventory | Constant-cardinality aggregate facts in `backend/src/eneo/object_content/reconciliation_repository.py:95-110,1065-1121` | Reuse and project into a sanitized admin contract |
| Tenant settings | Per-user row in `backend/src/eneo/database/tables/settings_table.py:11-15` | Deliberately not used for deployment policy |
| Frontend state | Tenant-admin layout and generated Eneo client | One admin storage page using generated contracts after authority is frozen |

## Verified Findings

1. The four legacy business settings are process-owned and have a closed
   runtime consumer set. Direct source reads occur only in `FileProtocol`,
   `TaskService`, `LimitService`, `AppAssembler`, and startup validation.
   Worker startup delegates to the same lifespan at
   `backend/src/eneo/worker/worker.py:266-279`, so a database read per admission
   or write is required for no-restart behavior across processes.
2. Production File and Icon writes hard-code PostgreSQL-inline. The PM confirmed
   that `ObjectContentService.store_and_verify()` at
   `backend/src/eneo/object_content/content_service.py:280-370` is called only
   by integration tests. Switching only `storage_kind` would therefore leave a
   pending control row without uploading bytes.
3. Existing `/admin` authorization is tenant `Permission.ADMIN`
   (`backend/src/eneo/roles/permissions.py:14-55` and
   `frontend/apps/web/src/routes/(app)/admin/+layout.ts:10-25`), while deployment
   sysadmin endpoints use the super API key
   (`backend/src/eneo/sysadmin/sysadmin_router.py:86-90`). The Judge must freeze
   a safe platform-admin authority before API or UI implementation.
4. The migration precedent for a one-time environment seed is
   `backend/alembic/versions/202607240310_add_skill_runtime_policies.py:21-97`.
   The new row needs positive database constraints, a full replacement
   mutation, an integer revision, and optimistic compare-and-swap to prevent
   lost concurrent updates.
5. `ObjectContentHealthFacts` already returns at most
   storage-kind × lifecycle-state rows plus scalar blockers. It uses five
   aggregate queries independent of file and tenant count. The admin projection
   must exclude object keys, endpoint, bucket, deployment identifiers,
   credentials, and raw failure details.

## Decisions the Judge Must Freeze

- Who can mutate deployment-wide policy without granting every tenant
  administrator cross-deployment authority.
- Exact eligible producers: user File uploads, generated File images, and Icon
  writes; knowledge/InfoBlob generation and Flow remain excluded.
- Object-store ceiling semantics and effective-limit projection.
- Full PUT plus `expected_revision` optimistic concurrency.
- Selection-time and later-outage behavior: no fallback, no dual write, and a
  stable sanitized 409/503 contract.
- Missing/invalid migration seed behavior and rollback expectations.
- Deployment-wide audit actor and action semantics.
- The target-aware producer transaction/upload lifecycle, including explicit
  failure recovery after the owner transaction commits.

## Candidate Worker Split

T003 should own the behavior-first backend/database vertical slice: typed
policy, migration, capability/inventory API, authority, container wiring,
effective-limit consumers, target-aware File/Icon lifecycle, legacy runtime
configuration deletion, and focused backend tests.

T004 should own the stabilized generated client, admin UI, both locales,
deployment/docs-site documentation, and exact validation evidence.

Both tasks stop if the authority, lifecycle, or migration contract remains
ambiguous, the migration base changes, or the same unexplained verification
failure repeats twice.

## Risk and Confidence

- Platform-admin authority: high risk, high confidence that current tenant
  `ADMIN` is insufficient without an explicit product decision.
- Remote producer lifecycle: high risk, high confidence.
- Policy persistence and optimistic concurrency: medium risk, high confidence.
- Reused bounded inventory: medium query-plan risk, high contract confidence.
- Legacy seed environment availability: medium risk, medium confidence until
  the Judge freezes failure and rollback behavior.
