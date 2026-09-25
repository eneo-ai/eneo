# T009 Option B frozen plan

## Decision

`ready_for_claude_plan_gate`

Option B is executable as three serial Worker commits. No implementation starts
until the revised plan receives `GREEN_LIGHT: yes` and `MIN_SCORE >= 8` from
the existing Claude session `eneo-admin-file-storage-settings`, with every
material claim independently verified.

## Authority contract

- `users.is_platform_admin BOOLEAN NOT NULL DEFAULT false` is the only
  session-backed deployment authority. Do not add a grant table, control
  tenant, generic authorization layer, or parallel identity.
- The flag exists on internal `UserInDB`, the existing `UserPublic`
  current-user/login projection, and the existing raw sysadmin user response.
  It is absent from tenant user create/update inputs, `UserAdminView`, and
  `UserSparse`; do not create a second current-user contract.
- `PUT /sysadmin/users/{user_id}/platform-admin` is idempotent and protected by
  the existing router-level super-key dependency.
- Grant requires an existing, real, non-system, non-deleted user in active
  state, an active tenant, and effective tenant `Permission.ADMIN`. Failure is
  a typed 409; a missing row is 404. The ADMIN check is a point-in-time grant
  precondition. Lock the user row only to serialize flag writes; do not pretend
  that lock serializes independent role-assignment rows.
- Revoke requires only that the database row exists, including soft-deleted,
  inactive, role-lost, or suspended targets. Already false is a successful
  no-op. It must not reconstruct a soft-deleted `UserInDB`.
- Dormant grants remain stored and super-key-visible/revocable but confer no
  privilege. Do not create cross-module auto-clear hooks.
- Policy GET is available to active tenant Admins. Policy PUT requires a fresh
  real bearer-session user with tenant Admin plus `is_platform_admin`. Every
  API-key caller is rejected; the browser never receives the super key.
- Session authentication reloads the user from PostgreSQL on every request,
  but the platform-admin mutation dependency itself must require
  `UserState.ACTIVE`, active tenant, current `Permission.ADMIN`, and the flag.
  Reuse `require_session_auth` and `require_user_identity`; do not create a
  third bearer/API-key fence. Grant, revoke, role loss, state change, deletion,
  and tenant suspension therefore affect the next request without token
  reissue or process restart.

## Policy and lifecycle contract

- One typed singleton deployment-policy row owns revision/CAS, new-write
  target, four positive business limits, timestamps,
  `updated_by_actor=migration|platform_admin`, and nullable
  `updated_by_user_id REFERENCES users(id) ON DELETE SET NULL`. Normal soft
  deletion preserves attribution; on rare hard deletion the actor enum and
  sanitized structured log remain truthful.
- The migration seeds revision 1 and `postgres_inline` exactly once. Present
  positive legacy values are preserved; absent fresh installs use
  10/10/10/200 MiB; blank, non-integer, zero, or negative values fail naming
  the variable. Restarts never overwrite the row.
- Preserve the five configured/effective/constraining-source projections and
  target-specific inline operator ceiling. Multipart protocol sizing is not a
  business ceiling.
- Capability output is sanitized. Inventory remains bounded to at most 12
  target/state rows and reuses the reconciliation repository aggregation.
- Eligible new `FileService.save_file` families and `IconService.create_icon`
  writes pin one target and policy revision. Generated SSE answer images via
  `save_image_from_bytes` remain PostgreSQL-inline in PR 1 because their
  streaming failure contract cannot safely provide aggregate compensation and
  an HTTP 503 after headers are sent.
  Target-aware capture uses the correct part sizing. Object-store writes
  complete verification before success; remote failure compensates the entire
  new aggregate so no failed File/Icon remains visible. No fallback, dual
  write, move, or successful pending aggregate exists.
- Policy mutation logs the actor user ID and old/new sanitized values/revision.
  Grant/revoke logs target ID and before/after state. Deployment events never
  enter the tenant audit table. A durable global audit store is deferred.

## Serial tasks and commit boundaries

### T003 — authority and policy foundation

Add the migration, user flag and intentional projections, locked super-key
grant/revoke, session platform-admin dependency, singleton policy repository
and CAS, sanitized admin GET/PUT implementation, capability/inventory
projections, and structured logging. Do not register the policy router yet,
change producers, or delete legacy runtime settings. This foundation commit is
intentionally inert and not independently deployable; T010 atomically
registers the API while migrating every consumer.

Red-first proof:

- default-false/user projection and writable-schema non-escalation;
- grant eligibility matrix, dormant/deleted revoke, idempotency, and serialized
  flag writes;
- bearer/user-key/service-key authorization matrix and immediate
  revoke/role/ACTIVE-state/tenant-state enforcement, including a `DELETED`
  state with null `deleted_at`;
- exact/absent/invalid migration seed, FK `SET NULL`, and downgrade/re-upgrade;
- CAS/read atomicity, sanitized capability/inventory, bounded query count and
  structured secret-free logs.

T012 resumes Claude over the exact intended/staged delta and focused validation
before commit 1.

### T010 — consumers and producer lifecycle

Move the closed limit readers to the persisted policy, register the policy API,
implement target-pinned File/Icon capture and compensating failure, and delete
the four runtime business Settings fields plus `required_inline_bytes`. Do not
touch the migration, frontend, or docs.

`POST /files/` and `POST /icons/` use the existing
`get_container(with_user=True, with_transaction=False)` path. Their existing
producer services own explicit transaction phases: capture all content, commit
metadata + intent + references, await `store_and_verify` outside that
transaction, then on failure delete the new File family or Icon in a second
explicit transaction before returning a sanitized 503. A successful response
is emitted only after all remote content is `AVAILABLE`. Generated SSE answer
images remain inline. Because the non-ambient dependency previously ran
`setup_user` outside a transaction, `_get_container_with_user` must wrap that
activation write in `session.begin()` only when no ambient transaction exists;
otherwise it reuses the ambient transaction. This also repairs existing
streaming callers without nesting transactions for ordinary endpoints.

The deployment-policy module owns one immutable typed business-limit snapshot.
Each closed async admission/projection entry point resolves it once and injects
it into `AppAssembler`, `LimitService`, `FileProtocol`, or an instance-bound
`TaskService`. Synchronous consumers stay synchronous after injection. There is
one bounded policy SELECT for a request/job that needs limits and zero added
reads for unrelated requests, with no cache, listener, per-consumer duplicate
reads, or legacy compatibility reader.

Red-first proof:

- five use cases accept maximum and reject maximum + 1;
- inline operator ceiling constrains only applicable paths;
- independently constructed API-style and worker-style containers observe a
  committed revision without restart;
- an inactive user's first File upload commits activation on the
  non-ambient-transaction path;
- `AppAssembler` accepted-file and aggregate limits reflect a committed policy
  change without restart;
- remote capture above multipart threshold uses the correct parts;
- unavailable/integrity failure leaves no visible File family or Icon;
- inline and compatible-store immediate reads are byte-identical;
- unchanged behavior for generated SSE answer images;
- no fallback, dual write, move, or unbounded database work.

Compensating File/Icon metadata deletion must reuse the existing reference
delete trigger and object-content reconciliation cleanup. Do not add a second
cleanup owner. Keep the File and Icon services as owners of their distinct
aggregates; shared capture/store mechanics remain in `ObjectContentService`
rather than a new cross-domain lifecycle helper. Run the failure assertion for
both producers and for a multi-content File family, not just one content row.

T013 resumes Claude before commit 2.

### T004 — generated contracts, admin UI, and docs

Regenerate exact OpenAPI types, add the ordinary policy client only, build the
editable/read-only admin storage page and translations, remove legacy
deployment configuration, and update docs.eneo.ai plus focused deployment
documentation. Do not add a browser grant/revoke wrapper.

Red-first proof:

- platform-admin tenant Admin can edit;
- ordinary tenant Admin sees the same sanitized state read-only;
- backend 403 remains authoritative;
- stale 409, unavailable target, operator ceiling, no-restart behavior, and
  no-move warning render clearly;
- generated/public schemas expose no infrastructure secrets.

T014 resumes Claude before commit 3.

### Final and publication gates

T005 runs the complete local exact-head gate and resumes Claude before the
first push. Every later review-fix commit and push receives a new resumed
Claude pre-commit/pre-push gate. T006 owns repository `/review` and CI loops.
T007 squash-merges only an immutable reviewed green head. T999 performs the
final merge/state audit.

## Canonical owners and deletion

- Identity authority: existing Users row/repository.
- Policy/CAS/projections: one deep `eneo.object_content` deployment-policy
  module/table.
- Admission snapshot: the deployment-policy module creates one immutable typed
  snapshot per limit-using request/job; the owning async entry point injects it
  into the applicable closed consumer.
- Capability: `ObjectContentRuntime`.
- Inventory: reconciliation repository.
- Capture: deepen `ObjectContentService`.
- Producers: existing `FileService` and `IconService`.
- UI state: generated current-user and policy contracts.
- Delete after consumers migrate: four runtime business settings,
  `required_inline_bytes`, active environment/template entries, and duplicate
  limit derivations. Do not leave a compatibility reader.

## Stop conditions

Stop for a required file outside the active scope, a second authority/policy
source, unsafe dormant-user revoke, unproven migration/FK safety, unbounded
facts/query work, remote failure that leaves a visible aggregate, unavailable
compatible-store prerequisites, or two unexplained repeats of the same
required validation failure.

The policy PUT intentionally follows the existing dependency pattern and may
perform two bounded user loads: the container's authenticated user and the
`require_session_auth`/`require_user_identity` guard. Do not replace those
existing fences with a custom combined dependency.

## Deferred

#569 PR 2 moves and cleanup UI; control tenant; per-tenant policy/routing/
buckets; grant history/global audit store; generic authorization; transcription
placement; knowledge/InfoBlob generation; Flow; provider registry/third
backend; #571; and #586 until a concrete consumer contract. This Goal stops
after the verified #569 PR 1 merge and audit.
