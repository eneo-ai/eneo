# T002A platform authority escalation

## Why implementation stopped

Issue #569 requires both:

- administrators can see and select the eligible default backend for new
  content; and
- an authorized platform administrator can change typed upload limits without
  backend or worker restart.

The frozen T002 plan allowed deployment mutation only through
`ENEO_SUPER_API_KEY` and made the existing browser admin page read-only. That
was secure, but it did not satisfy the accepted browser outcome. T003 was
therefore interrupted before any production/test change or test run.

The repository currently has two distinct authority levels:

- `Permission.ADMIN` is tenant/organization-scoped
  (`backend/src/eneo/roles/permissions.py:14-55` and
  `backend/src/eneo/server/api_documentation.py:89`).
- deployment-wide sysadmin operations require `ENEO_SUPER_API_KEY`
  (`backend/src/eneo/sysadmin/sysadmin_router.py:86-90` and
  `backend/src/eneo/server/api_documentation.py:96-101`).

There is no session-backed platform-administrator capability. The current
browser admin layout admits tenant admins
(`frontend/apps/web/src/routes/(app)/admin/+layout.ts:10-25`). Allowing that
role to update a singleton deployment policy would let an administrator of one
tenant change behavior for every tenant.

## Option A: tenant Admin mutates under an explicit deployment assumption

### Shape

Keep the existing `Permission.ADMIN` session boundary and add editable
GET/PUT controls to the existing admin page. The deployment must explicitly
declare that tenant administrators are also trusted as deployment
administrators.

A safer variant would require an operator-owned designation of one control
tenant and authorize only its tenant admins. There is no current canonical
control-tenant setting, so this still adds a new deployment trust convention.
Authorizing every tenant admin is unacceptable for a multi-tenant deployment.

### Extra scope

- A deployment-mode/control-tenant authority setting and startup validation.
- A backend guard combining session auth, tenant Admin, and that deployment
  designation.
- UI state explaining the deployment trust mode.
- Tests proving other tenants cannot mutate, designation changes are explicit,
  and missing/ambiguous designation fails closed.

### Risks

- Conflicts with Eneo's documented tenant/deployment authority split.
- A configuration mistake grants cross-tenant control.
- Authority remains restart/configuration-dependent even though the business
  policy does not.
- A control-tenant convention is product architecture, not storage policy, and
  becomes a long-lived hidden root of trust.

### Assessment

Only acceptable if the product owner explicitly declares single-tenant or
control-tenant deployment trust as a supported invariant. It is not safe as an
implicit shortcut and is not recommended for the current multi-tenant product.

## Option B: add a session-backed platform-administrator capability

### Shape

Add an explicit `is_platform_admin` boolean to the canonical user identity.
It defaults false and is never present in tenant user-create/update inputs.
Only `ENEO_SUPER_API_KEY` may grant or revoke it through a dedicated sysadmin
endpoint. The existing browser session exposes the read-only flag through
`/users/me`.

The deployment-policy page remains inside the existing admin panel:

- all tenant Admins may read the sanitized capability, inventory, configured,
  and effective values;
- only a real session user with both tenant `Permission.ADMIN` and
  `is_platform_admin=true` sees and may submit the edit form;
- API keys, service keys, tenant user-management endpoints, and ordinary tenant
  admins cannot mutate the singleton;
- the super key is used only to bootstrap/revoke the capability and is never
  sent to the browser.

The policy row records `updated_by_user_id` plus non-secret old/new values and
revision in the structured operational log. Tenant audit storage remains
inapplicable because the event is deployment-wide.

### Extra scope

- One user-table migration field plus the policy-table migration.
- User ORM/domain/public projections and generated client types.
- Super-key-only grant/revoke endpoint and tests for self-escalation,
  tenant-admin escalation, inactive/deleted users, role removal, and session/API
  key distinctions.
- A `require_platform_admin` dependency at the policy PUT boundary.
- Admin navigation/form gating and English/Swedish explanations.
- Updated audit attribution and rollback docs.

### Risks

- Expands PR 1 into identity/authorization and requires a focused threat review.
- Grant lifecycle must remain super-key-owned and fail closed.
- A user can retain the stored flag after losing tenant Admin; requiring both
  permissions prevents access but the dormant grant must remain visible to
  operators.
- Adds generated-contract and migration surface.

### Assessment

This is the smallest option that satisfies the accepted editable browser
outcome while preserving tenant fences. Recommended if the user accepts the
explicit auth expansion inside issue #569 PR 1.

## Option C: super-key mutation plus read-only admin UI

### Shape

Keep the original T002 decision: super-key-only GET/PUT on the sysadmin API,
with a read-only tenant-admin page showing configuration, effective limits,
capability, inventory, and operator instructions.

### Extra scope

No identity model change. Backend policy, producers, migration, generated
read contract, and read-only page proceed as frozen.

### Risks

- Does not meet issue #569's accepted requirement that administrators can
  select the backend and change limits in the admin UI.
- Requires an operator/API workflow for every change.
- PR 1 must be described as a reduced/partial outcome and cannot close or claim
  completion of issue #569.

### Assessment

Secure and smallest, but only valid if the user knowingly reduces the accepted
outcome and schedules a separate platform-admin UI/auth follow-up.

## Recommendation

Choose Option B. It adds real scope, but it creates an explicit, revocable,
session-backed authority instead of weakening tenant isolation or pretending a
read-only page meets the issue.

No option may place `ENEO_SUPER_API_KEY` in browser state, authorize every
tenant Admin implicitly, introduce per-tenant storage policy, or weaken the
deployment-wide singleton contract.

## Option B implementation-ready boundary

This section is preparatory only. It does not authorize implementation before
the owner selects Option B.

### Canonical owner

The capability belongs on the canonical user identity as
`users.is_platform_admin BOOLEAN NOT NULL DEFAULT false`.

- The existing user repository loads the ORM row on each session-authenticated
  request (`backend/src/eneo/users/user_service.py:741-747,1674-1692`), so a
  grant or revoke takes effect without a new session, token claim, cache, or
  process restart.
- The schema shape follows the existing `is_system_user` boolean precedent
  (`backend/src/eneo/database/tables/users_table.py:25-40` and
  `backend/alembic/versions/202605211000_add_users_is_system_user.py:27-53`).
- A separate grant table would add a query and parallel identity ownership
  without improving the single boolean invariant.

The field must be absent from `UserAdd`, `UserUpdate`, `UserAddAdmin`, and
`UserUpdatePublic`, so tenant user CRUD cannot assign it
(`backend/src/eneo/users/user.py:206-244,338-389`). Only a dedicated repository
method called by the super-key sysadmin adapter may update it.

### Grant and revoke

Add one super-key-only full-replacement endpoint:

`PUT /api/v1/sysadmin/users/{user_id}/platform-admin`

with typed body `{ "enabled": true|false }`.

Grant must fail closed unless the target:

- exists and is not soft-deleted or a system user;
- is active and belongs to an active tenant;
- currently has tenant `Permission.ADMIN`.

Revoke must remain available even when the target becomes inactive or loses
the tenant role, so the operator can remove dormant grants. The endpoint never
returns or accepts the super key in its body or response. It emits only a
structured non-secret operational event; durable deployment audit history
remains the separately identified platform audit gap.

No browser wrapper or admin-panel grant management belongs in PR 1. Operators
bootstrap the first platform administrator using the existing super-key
channel.

### Session mutation boundary

Add one dependency that composes:

1. current active user loading;
2. `require_session_auth`, rejecting user-owned and service API keys;
3. tenant `Permission.ADMIN`;
4. `user.is_platform_admin`.

The deployment-policy PUT uses that dependency. The GET remains available to
ordinary tenant Admins. Because authentication reloads the database user each
request, grant, revoke, inactivity, deletion, tenant suspension, and role loss
all affect the next request without token reissue or restart.

The policy row changes its attribution from the provisional enum-only owner to:

- `updated_by_actor = migration|platform_admin`;
- nullable `updated_by_user_id` FK with `ON DELETE SET NULL`;
- revision and timestamps.

Migration seeding uses `migration` and null user ID. Browser updates use the
authenticated user ID. The structured policy-change log contains that user ID,
old/new non-secret policy values, and revisions, but no tenant audit row.

### Browser projection

Expose `is_platform_admin` only on the current-user response used by the app
context (`backend/src/eneo/users/user_router.py:746-767` and
`frontend/apps/web/src/lib/core/AppContext.ts:15-55`), not on tenant user
create/update payloads.

The existing `/admin` layout remains tenant-Admin-only. All tenant Admins may
open the storage page and inspect sanitized facts. The generated
current-user flag controls whether edit controls render; the backend dependency
is authoritative. Non-platform tenant Admins see a clear read-only explanation.

### Required auth tests

- Tenant Admin without the flag: GET 200, PUT 403.
- Platform flag without tenant Admin: PUT 403 and edit controls hidden.
- Both capabilities with a real session: PUT succeeds.
- User-owned API key and service key: PUT 403 even if the owner is a platform
  admin.
- Grant/revoke is 401 without the correct super key.
- Tenant Admin user CRUD cannot bind or change the flag.
- Grant refuses non-admin, inactive, deleted, system-user, or
  suspended-tenant targets.
- Revoke succeeds for dormant targets.
- Grant/revoke is visible on the next authenticated request without token
  reissue or process restart.
- Soft deletion, inactivity, tenant suspension, role loss, and revoke all block
  policy mutation immediately.
- OpenAPI and generated clients expose typed current-user/read/update contracts
  without adding a browser-facing super-key method.

### Option B scope delta

If selected, the revised backend Worker must additionally own:

- the user-table migration/ORM/Pydantic current-user projection;
- a narrow user-repository grant setter;
- the super-key sysadmin grant endpoint;
- the session platform-admin dependency;
- focused identity/auth/API tests.

The frontend Worker must additionally own current-user generated types and
editable-vs-read-only component behavior. Claude Pass 2 and the PR review must
include a focused authorization/threat-model gate.
