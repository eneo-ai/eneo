# Phase 3 — API/data layer: typed client, proxy, TanStack Query

## Goal
A typed, auth-injecting data layer the rest of the migration builds on: OpenAPI-generated types + `openapi-fetch` client, a catch-all REST proxy route handler for client-side calls, TanStack Query v5 with the App Router hydration pattern, normalized error handling (error-code → i18n message, trace-id surfacing), and a first real page (`/dashboard` listing spaces/assistants from `GET /api/v1/dashboard/`) proving the stack end-to-end.

## Prerequisites
- Phase 2 gate green (`getAccessToken()` works for both session modes).
- Backend reachable at `ENEO_BACKEND_URL` (dev: `http://localhost:8123` from the host; verify the in-container hostname, the Svelte app uses a separate `ENEO_BACKEND_SERVER_URL` for server-to-server calls; replicate that env split if the devcontainer network needs it).

## Scope
**In**: type generation pipeline, `eneoFetch` server-side client, `/api/eneo/[...path]` proxy, QueryClient setup + `HydrationBoundary` helpers, error normalization + toasts (sonner), 401-handling (clear session, redirect to login), the dashboard list page, schema-drift CI check.
**Out**: chat streaming (Phase 5 has its own route handler), file uploads (Phase 6), any mutation-heavy UI.

## Design
- **Types**: reuse the existing pipeline concept from `frontend/packages/intric-js` (which runs `openapi-typescript` against the backend's `/openapi.json`). Add a script in `web-next`: `bun run gen:api` → fetch `${ENEO_BACKEND_URL}/openapi.json` → `openapi-typescript` → `src/lib/api/schema.d.ts`. Commit the generated file; CI compares freshly generated output against the committed one (mirrors the existing "schema drift" CI job; reuse its approach).
- **Client**: `openapi-fetch` typed against the schema. `src/lib/api/server.ts` exposes `eneoApi()` which builds a client with `baseUrl = ENEO_BACKEND_URL` and `Authorization: Bearer ${await getAccessToken()}`. Server-only (`import "server-only"`).
- **Browser path**: client components never call the backend directly (no token in the browser). `src/app/api/eneo/[...path]/route.ts` proxies GET/POST/PATCH/PUT/DELETE to `${ENEO_BACKEND_URL}/api/v1/${path}`, injecting the bearer token, streaming bodies through, passing query strings, and forwarding `X-Trace-Id` back. Allowlist nothing for now (session-authenticated users hit the same backend authz they would directly); deny if no session (401 JSON).
- **TanStack Query**: per-request `QueryClient` helper (`makeQueryClient` + `cache()`), `prefetchQuery` in server components + `<HydrationBoundary state={dehydrate(qc)}>`, client hooks built on a small `browserApi` (openapi-fetch with `baseUrl: "/api/eneo"`). Convention: query keys mirror backend paths (`["spaces", spaceId]`, `["dashboard"]`).
- **Errors**: one `EneoApiError` carrying `status`, `code` (backend `intric_error_code` or `detail.code`), `message`, `traceId` (from `X-Trace-Id`/`X-Correlation-ID`). Parse all three known `detail` shapes (string, object, validation array). Map codes → i18n keys (port the mapping from the Svelte app's `getErrorMessage`). Toasts via sonner with the trace-id in an expandable detail. On 401: server side → clear session + redirect `/login?next=`; client side → full reload to let the server path handle it.
- **RB-5 stance**: code the client against the clean shapes (cursor pagination helper, `{items, …}` list wrapper). Where the backend deviates (offset pagination on `/admin/users/` and audit logs, POST-as-update on assistants), wrap per-endpoint with a `// RB-5(x)` comment so the workaround inventory stays greppable. Raise RB-5 as a backend tracking issue now; individual cleanups land opportunistically.

## Step-by-step
1. Add deps: `openapi-typescript` (dev), `openapi-fetch`, `@tanstack/react-query` ^5, `@tanstack/react-query-devtools` (dev), `sonner`.
2. `gen:api` script + commit `schema.d.ts`; CI drift check.
3. `src/lib/api/{server.ts, browser.ts, errors.ts, query.ts}` + unit tests for error parsing (all three detail shapes, trace-id extraction) and the cursor-pagination helper.
4. Proxy route handler + tests (mock session: forwards method/query/body, injects header, 401 when no session).
5. Providers: add `QueryClientProvider` + sonner `<Toaster>` to the root layout.
6. Rebuild `/dashboard` as the proving page: server component prefetches `dashboard.list` (`GET /api/v1/dashboard/`), client component renders spaces with assistant/app counts via `useQuery` (hydrated, no client refetch on load), plus a deliberate error path (e.g. a button querying a nonexistent id) showing the toast with trace-id.
7. Remove the Phase 2 smoke component.

## Files/structure created
```
src/lib/api/{schema.d.ts (generated), server.ts, browser.ts, errors.ts, query.ts, pagination.ts}
src/app/api/eneo/[...path]/route.ts
src/app/(app)/dashboard/page.tsx (+ dashboard-list.client.tsx)
src/components/providers.tsx
scripts/gen-api.ts (or package.json script)
+ tests: src/lib/api/*.test.ts, route handler tests
```

## VALIDATION GATE
1. `bun run gen:api` is idempotent against the running dev backend (second run produces no diff) and `bun run check` passes against the generated types.
2. `bun run test` — error-parsing, pagination, and proxy tests green.
3. Manual: logged in (either mode), `/dashboard` server-renders real spaces (view-source shows the data, proving SSR prefetch); React Query devtools show a hydrated, non-refetching query.
4. Manual: the deliberate error button shows a toast with a human message and a trace-id that matches the backend log line (grep backend logs for it).
5. Manual: expire/delete the session cookie, click a client-side refetch → lands on `/login?next=/dashboard`, then logging in returns to `/dashboard`.
6. `curl -s http://localhost:3100/api/eneo/spaces/` without a cookie → 401 JSON, never a 500.
7. CI: drift check + all jobs green.

## Exit criteria
Any later phase can fetch typed data in a server component (`eneoApi()`), in a client component (`useQuery` + proxy), and handle errors uniformly; dashboard proves all three.

## Risks / unknowns
- The backend OpenAPI spec may under-specify some response shapes (the Svelte client hand-patches types in `resources.d.ts`). Keep a `src/lib/api/overrides.ts` for the same purpose; record each override as an RB-5 candidate.
- Proxy streaming/body edge cases (multipart goes through here in Phase 6; verify `duplex: "half"` requirements when forwarding request streams in Node).
- Devcontainer networking: confirm what hostname the Next server uses to reach the backend (the Svelte app distinguishes browser URL vs server URL; web-next only needs the server one).
