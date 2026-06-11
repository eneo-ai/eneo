# Phase 7 — Admin area

## Goal
Full organization administration: feature toggles, user management, audit logs (with the async-export BFF), model/provider management incl. migration flow, security classifications, MCP servers, org API keys, tenant integrations, templates administration, help assistants, insights, and usage.

## Prerequisites
- Phase 6 gate green.
- Decision on overview **OQ-2** (legacy roles/user-groups: plan assumes DROP) and **OQ-5** (charts via shadcn charts/recharts).
- Source references: `frontend/apps/web/src/routes/(app)/admin/**`, audit BFF handlers under `admin/audit-logs/export/`.

## Scope
**In**:
- `/admin`: tenant feature toggles (templates, audit logging, provisioning) with optimistic update + revert-on-error (`PATCH /api/v1/settings/{feature}`).
- `/admin/users`: list (search by email/name, state tabs, offset pagination — wrap and tag `RB-5(a)`), create, invite, edit, activate/deactivate.
- `/admin/audit-logs`: filter UI (date range, action multi-select, actor, full-text), table, retention-policy panel, justification "access session" prompt (`POST /api/v1/audit/access-session`, cookie-based today — forward that cookie through the proxy; tag `RB-5(d)`), async export: Next route handlers replacing the four SvelteKit BFF endpoints (start job, poll status, download, cancel).
- `/admin/models`: model list/edit (enable/disable, capabilities), providers + favorites, tenant credentials (if enabled), security-classification assignment, model migration flow (validate → migrate → history) including its multi-step wizard.
- `/admin/security-classifications`: CRUD.
- `/admin/mcp-servers`: list, enable/disable per org, settings, classifications, tools display.
- `/admin/api-keys`: org-scoped key management (reuse the account api-keys feature components).
- `/admin/integrations`: tenant provider enable/disable, SharePoint subscription admin (list, renew-expired, recreate).
- `/admin/templates`: assistant + app template CRUD, soft-delete/restore/permanent-delete, rollback, featured toggle, new/edit forms per kind.
- `/admin/help-assistants`: installed roles vs available templates, install/uninstall, per-kind config page.
- `/admin/insights`: org analytics (30-day aggregates, charts), per-assistant analytics list + detail (time series); the insights "ask the analysis assistant" stream uses the same v3 protocol if the analysis endpoint gets it, otherwise defer that one widget and tag it.
- `/admin/usage`: tokens/storage tabs, per-user detail.
**Out** (assumed DROP per OQ-2): `/admin/legacy/roles`, `/admin/legacy/user-groups`. If OQ-2 says keep, add a 7b addendum.

## Design notes
- All admin routes double-gate: nav hidden without `admin` permission AND server-side `requireSession()` + permission check in the layout (`/admin/layout.tsx`).
- Audit-log table: build on TanStack Table with server-side filtering via query params kept in the URL (today's page does this; preserves shareable filtered links).
- Export BFF route handlers mirror today's contract: `POST /admin/audit-logs/export/async` → `{job_id}`; `GET .../[job_id]/status` → progress; `GET .../[job_id]/download` → streamed file; `POST .../[job_id]/cancel`. They proxy to `/api/v1/audit/logs/export/...` with bearer + audit-session cookie.
- Insights charts: shadcn charts (recharts) line/bar; keep the data hooks separate from chart components so a later charting swap is cheap.
- Model migration wizard: multi-step dialog (validate → confirm impact → migrate → link to history); the backend contract is already clean.

## Step-by-step
1. Admin layout + gating + nav.
2. Feature toggles page (small, proves the optimistic-update pattern for the area).
3. Users management.
4. Audit logs (filters → table → retention → access-session prompt → export BFF).
5. Models (+ providers, credentials, migration wizard) and security classifications.
6. MCP servers, org API keys, tenant integrations (+ SharePoint subscriptions).
7. Templates admin (+ new/edit forms), help assistants.
8. Insights + usage.

## Files/structure created (representative)
```
src/app/(app)/admin/layout.tsx
src/app/(app)/admin/{page.tsx, users/, audit-logs/, models/, security-classifications/, mcp-servers/, api-keys/, integrations/, templates/, help-assistants/, insights/, usage/}
src/app/api/admin/audit-export/{route.ts, [jobId]/{status,download,cancel}/route.ts}
src/features/admin/…
```

## VALIDATION GATE
1. `bun run check && bun run lint && bun run test && bun run build` — green.
2. Manual, as an admin user against the dev backend:
   - Non-admin user gets 404/redirect on every `/admin/*` URL typed directly.
   - Toggle templates feature off → space assistant-creation loses the template picker (cross-phase integration check); toggle back.
   - Create + invite a user; deactivate → that user's next request lands on `/deactivated`; reactivate.
   - Audit logs: justification prompt appears once per session; filter by action + date; export async → poll → download a non-empty CSV; cancel a running export.
   - Disable a completion model → it disappears from space settings selectors; run the migration validate flow on a test model and inspect the impact report (do not migrate prod-ish data).
   - Create/edit/soft-delete/restore an assistant template; featured toggle reflected in the space template picker.
   - MCP server enable/disable reflected in the assistant editor's attach list.
   - Insights pages render charts with real aggregates; usage tabs show token/storage numbers matching the Svelte app side-by-side.
3. RB-5 workaround inventory updated (offset pagination wrappers, audit cookie forwarding).

## Exit criteria
An org admin can run the platform from web-next alone; the four audit-export BFF endpoints behave identically to the SvelteKit ones.

## Risks / unknowns
- Audit "access session" cookie semantics through the proxy (domain/path of the backend-set cookie); may need the proxy to re-scope the cookie. Spike this first within the audit work.
- Insights analysis-assistant streaming depends on whether the analysis endpoint also gains v3 (small backend addition); the widget is deferrable.
- Charts parity is approximate by design (OQ-5).
