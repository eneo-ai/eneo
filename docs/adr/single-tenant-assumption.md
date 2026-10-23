# Single-tenant assumption

- **Status:** Accepted
- **Date:** 2026-10-01
- **Decision owners:** Product and architecture
- **Scope:** New backend, frontend, settings, and documentation work in Flow and
  the Flow AI Builder; existing code is not rewritten by this record

## Context

Eneo's storage and settings are keyed by tenant because the platform was built
to host several organizations in one deployment. Multi-tenancy will be dropped.
Every code path, setting, test, and message that treats the tenant as a
variable adds complexity for a case the product will not support: fan-out over
tenants, per-tenant limits that differ from the server's capacity, isolation
logic between tenants, and the word "tenant" in the admin UI and docs.

## Decision

- New work assumes one tenant per deployment.
- A deployment-wide setting is either an admin setting of that one tenant or an
  environment value that states server capacity. An admin setting is bounded by
  the capacity and defaults to it; a value equal to the capacity is stored as no
  override.
- New work adds no per-tenant fan-out, no tenant isolation logic, and no tenant
  wording in names, UI, docs, or messages. Name a setting by what it limits.
- Existing tenant-keyed storage is reused as it is until the tenant layer is
  removed. Code that still needs a tenant id passes the single tenant's id.
- Cross-tenant scenarios are out of scope for the review and tests of new work.
  Security is still enforced per user, space, and permission.

## Consequences

- Settings and the admin UI stay simple: one number, one bound, one hint.
- Removing the tenant layer becomes its own future change. It does not have to
  be prepared by new work, and new work does not have to undo it later.
- Existing public contracts that mention the tenant keep their names until that
  change; this record does not rename them.

## Example

Max concurrent flow runs is a field in the flow runtime policy
(`PATCH /api/v1/settings/flow-runtime-policy`). The server capacity bounds it:
the execution worker's slots (`TASK_EXECUTION_MAX_JOBS`), unless the operator
set `FLOW_MAX_CONCURRENT_RUNS_PER_TENANT`, whose existing meaning is kept. The
admin page shows the capacity next to the field, and the run capacity route
reports the effective value.
