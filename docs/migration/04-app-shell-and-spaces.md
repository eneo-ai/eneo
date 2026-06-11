# Phase 4 — App shell, dashboard, spaces, account

## Goal
The structural skeleton users live in: real header/navigation (permission-aware), the dashboard, spaces list + space sub-navigation, space overview/members/settings, and the account pages. After this phase the app is navigable end-to-end with everything except chat, builders, knowledge, and admin.

## Prerequisites
- Phase 3 gate green (typed client, proxy, Query, error handling).
- Familiarity with the source routes: `frontend/apps/web/src/routes/(app)/{dashboard,spaces,account}` and `AppContext.ts` (what global data the shell needs: user, tenant, settings, limits, feature flags, versions).

## Scope
**In**:
- App context loading: `/users/me/`, `/users/tenant/`, `/settings/`, `/limits/`, `/version`; permission helper (`hasPermission` port: roles + predefined_roles flatten, anyOf/allOf support); feature flags (env + tenant settings).
- Shell: header (nav: Personal/Spaces/Organization/Admin by permission; profile menu; language + theme switchers), space-scoped sidebar layout under `/spaces/[spaceId]`.
- Dashboard (`/dashboard`): spaces → assistants/apps accordion with links into chat/app routes (links can 404 until Phases 5–6; acceptable mid-migration since web-next is not user-facing yet).
- Spaces: `/spaces/list` (table + create dialog + delete), `/spaces/[spaceId]/overview` (tiles), `/members` (add/edit/remove members and group-members with roles), `/settings` (name/description, completion/embedding/transcription model selection, security classification, storage/retention; MCP-server section can stub until Phase 6 if its API surface drags).
- Account: `/account` (profile, language), `/account/api-keys` (full CRUD: create with secret reveal, rotate, revoke, scopes, state filter, expiry notifications), `/account/integrations` (list + disconnect; the OAuth connect popup flow lands in Phase 6 with the rest of integrations).
- Redirect plumbing: `/` → default landing, `/spaces/[spaceId]` → overview-or-personal-chat redirect.
**Out**: chat (5), assistant/app/service/group-chat builders and knowledge (6), admin (7), `/invite` + `/activate` (include here ONLY if Phase 2 verification said they survive the new auth model; see overview OQ-8).

## Design notes
- UI flows may be redesigned: rebuild tables on shadcn `Table` + TanStack Table where filtering/sorting exists; dialogs on shadcn `Dialog`; forms on `react-hook-form` + zod resolvers (add both here). Do not pixel-copy Svelte markup.
- Component sourcing (standing rule from Phase 1): primitives only from `src/components/ui`; missing shadcn components are CLI-installed, never hand-rolled. This phase is where most generic composites are born; put them in `src/components/composites/` (expected: data-table with server-side pagination/filter wiring, form-field wrapper, page-header, confirm-dialog, empty-state, secret-reveal for API keys) so Phases 5–7 reuse them. Route-specific compositions stay under `src/features/`.
- Server state stays in Query; the "app context" (user/tenant/settings) is fetched in the `(app)` layout server component and passed via a small React context provider; mutations invalidate by key.
- Mutations: server actions for simple form posts (space create/rename), Query mutations for interactive flows (member role changes, api-key rotation). Pick per-surface, stay consistent within a page.
- i18n: port the message keys each page needs (re-run the conversion script scoped to used keys); Swedish remains the base language and the default.
- Note for the API-keys page: it exercises cursor pagination + state filters; build the reusable `usePaginatedQuery` helper here and reuse it for chat history (Phase 5) and admin lists (Phase 7).

## Step-by-step
1. App context: layout-level fetches (parallel `Promise.all`), context provider, `hasPermission` port with unit tests (single, anyOf, allOf, empty roles).
2. Header/nav with permission-gated items; profile menu (account link, logout); reuse Phase 1 theme/language switchers.
3. `/spaces/list` + create/delete; space layout (`/spaces/[spaceId]/layout.tsx`) fetching the space + sidebar nav gated by space permissions.
4. Overview, members (member + group-member sections, role dropdowns, current-user marker), settings (form sections; model multi-selects from `GET /api/v1/ai-models/?space_id=`; retention/storage panel).
5. Dashboard accordion (data from `GET /api/v1/dashboard/`; preserve the "only spaces with content" filter).
6. Account pages incl. the full api-keys feature and `usePaginatedQuery`.
7. Redirects (`/`, `/spaces/[spaceId]`, `/spaces` → `/spaces/list`).

## Files/structure created (representative)
```
src/app/(app)/layout.tsx                      app context + shell
src/components/shell/{header.tsx, nav.tsx, profile-menu.tsx}
src/lib/auth/permissions.ts (+ test)
src/app/(app)/dashboard/page.tsx              (replaces Phase 3 proving page)
src/app/(app)/spaces/{page.tsx, list/page.tsx}
src/app/(app)/spaces/[spaceId]/{layout.tsx, route-redirect, overview/, members/, settings/}
src/app/(app)/account/{page.tsx, api-keys/, integrations/}
src/lib/hooks/use-paginated-query.ts
```

## VALIDATION GATE
1. `bun run check && bun run lint && bun run test && bun run build` — green.
2. Manual walkthrough against the dev backend, with two users (one admin, one plain member):
   - Admin sees the Admin nav item; the plain user does not. A user without `shared_spaces` cannot see the create-space button.
   - Create a space → appears in list and dashboard; rename in settings → reflected after invalidation without full reload; delete → gone.
   - Add the second user as viewer → their view of the space hides edit affordances; promote to editor → affordances appear.
   - Change completion-model selection in settings → persisted (verify via GET).
   - Create an API key (secret shown exactly once), rotate it, revoke it; state filter shows it under the right tab.
   - Language switch to English re-renders shell + visited pages translated; Swedish is default.
3. Parity spot-check against the Svelte app side-by-side (3000 vs 3100) for the same user: same spaces, same members, same settings values.
4. No browser request to `ENEO_BACKEND_URL` in devtools network tab; everything goes via `/api/eneo/*` or SSR.

## Exit criteria
A user can log in, navigate every shell-level surface, and manage spaces/members/settings/account with capability parity; dashboard links to chat/apps exist (target phases pending).

## Risks / unknowns
- Space settings is the densest form surface (multi-selects, classifications, retention); timebox MCP-server settings to a stub if needed (Phase 6 owns MCP UI).
- Group-member management depends on user-group endpoints whose admin UI is legacy (overview OQ-2); the space-members surface itself is NOT legacy and must work.
- The dashboard's sessionStorage scroll preservation is a nice-to-have; skip unless trivial.
