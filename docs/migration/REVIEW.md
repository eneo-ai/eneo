# web-next migration review plan

A deep, phase-by-phase review of the `apps/web` (Svelte) → `apps/web-next`
(Next) migration. Goal: confirm parity (looks the same, behaves the same,
handled the same), confirm correctness/security, and — since we're rewriting
anyway — deliberately flag where the new code should be *smarter* for
long-term maintainability, not just a 1:1 port.

We take **one phase per session**, in order. Findings are logged in this file
(NOT GitHub — stealth POC). Each finding gets a severity and a disposition
(fix-now / accept / defer-with-note).

## How we review each phase (fixed rubric)

Apply all eight dimensions to every phase; the per-phase sections below only
add what's *unique/risky* on top of this baseline.

1. **Parity (visual + behavioral)** — side-by-side vs the Svelte route. Same
   layout/affordances, same states (loading/empty/error), same edge cases,
   same copy. Note intentional redesigns explicitly (they're not gaps).
2. **API / contract fidelity** — endpoint paths, HTTP methods, request/response
   shapes vs `schema.d.ts`; RB-5 POST-as-update sites; query params; error-code
   handling. The thing the UI sends must match what the backend expects.
3. **Correctness** — logic, edge cases, races, optimistic-update + revert,
   pagination, debounce, cleanup (effects/object URLs/abort), null/empty.
4. **Security & auth** — token never reaches the browser; permission gating
   (tenant `can()` + space `can()` + server-side for `/admin`); cookie scoping;
   the audit access-session spike; no secrets in client bundles/logs.
5. **Maintainability / sustainability ("smarter now")** — structure &
   convention consistency, schema-driven types (no stray `any`/casts),
   duplication vs shared composites, dead code, comment quality, testability
   (pure logic extracted + unit-tested). Call out concrete refactors.
6. **Accessibility** — labels/aria, focus management, dialog focus traps,
   keyboard nav, `aria-current`, alt text.
7. **i18n** — sv/en parity, no hardcoded human text, ICU params correct,
   Swedish-default sanity.
8. **Performance** — query keys & invalidation breadth, over-fetching,
   RSC/`"use client"` boundary placement, `keepPreviousData`, bundle weight.

### Severity & disposition

- **S0 blocker** — wrong/broken/insecure; must fix before cutover.
- **S1 parity gap** — user-visible behavior differs from Svelte (unintended).
- **S2 bug** — edge-case/correctness issue, not blocking.
- **S3 maintainability** — works, but should be refactored for the long term.
- **S4 enhancement** — "smarter now" opportunity beyond the original.

Disposition per finding: **fix-now** · **accept** (with reason) · **defer**
(tracked here / in PARITY.md).

### Tooling / method (the "smart tools")

- **Source diffing**: read the Svelte feature (`apps/web/.../*.svelte`) next to
  the web-next feature; for breadth, fan out parallel `Explore` agents to map
  "Svelte does X / web-next does Y" across a feature area.
- **Run it**: use the `run`/`verify` skills to drive both apps and compare the
  same flow visually + behaviorally (login `alexander.andersson@sundsvall.se`
  / `Password1!`; backend + `bun run dev` on 3100 started by the developer).
- **Static**: `bun run check` (tsc), `bun run lint` (eslint+prettier),
  `bun run test` (vitest) — already green; re-run per phase. Targeted greps for
  anti-patterns: `as any`, `eslint-disable`, `console.log`, raw hex colors,
  hardcoded JSX text, `@ts-expect-error`, `TODO`.
- **Contract**: cross-check each call against `src/lib/api/schema.d.ts`.
- **Review pass**: `/code-review` on the phase's commits for an adversarial
  second opinion; promising findings get verified before logging.
- Pure logic gets a **unit test** added when reviewing reveals it lacks one.

## Cross-cutting checks (run once, not per phase)

- [ ] Repo-wide grep: `as any`, `@ts-expect-error`, `eslint-disable`,
      `console.log`, `TODO`/`FIXME`, raw color hexes in `src` — triage each.
- [ ] Convention audit: features under `src/features/*`, route files thin,
      `eneoApi()` (server) vs `browserApi` (client) used correctly, `unwrap()`
      + `toastApiError` everywhere, query-key naming consistent.
- [ ] Schema drift: regenerate `schema.d.ts`, confirm no diff.
- [ ] Bundle/RSC: spot-check that big client components are actually needed as
      client; server-first where possible.
- [ ] Dead i18n keys: scan `extra/{en,sv}` for keys no longer referenced.

---

## Per-phase review focus

### Phase 1 — Boilerplate / foundation
Unique risks: project config and the conventions everything inherits.
- next.config (standalone, headers, skipTrailingSlashRedirect) + `src/proxy.ts`
  trailing-slash logic — correct and not double-handling.
- Tailwind v4 + shadcn setup; eneo theme tokens in `app/globals.css`; the
  `dark:` variant behaviour; no raw colors.
- env.ts zod schema vs `.env.example` vs ENV.md — all three agree.
- Tooling parity: tsconfig strictness (`noUncheckedIndexedAccess` is on — good),
  eslint config, prettier, vitest config.

### Phase 2 — Auth (OIDC + password, RB-1)
Unique risks: security-critical; the most important phase to get right.
- OIDC: discovery, state/nonce/PKCE, callback validation, redirect-URI build
  from `APP_ORIGIN`, token exchange, error paths. Compare to the Svelte/Zitadel
  flow's guarantees (what did Zitadel enforce that we now must?).
- Session cookie: `jose` encryption, cookie flags (HttpOnly/Secure/SameSite/
  path/expiry), rotation, refresh-token handling, session-codec tests.
- Password mode parity; logout clears everything; deactivated/activate routes.
- **Verify** no token is ever exposed to client JS.

### Phase 3 — API layer (typed client, proxy, Query)
Unique risks: every feature sits on this.
- Proxy route: header allow-list (request + response), error body mapping →
  `EneoApiError` (status/code/traceId), streaming body (`duplex: half`), the
  new audit-cookie forwarding (re-review the scoping — does it ever leak the
  session cookie? path-rewrite regex robustness).
- `unwrap()`/error model; SSR `fetchQuery` (not `prefetchQuery` — the 401
  swallow) consistently applied; HydrationBoundary usage.
- Query-key conventions documented vs actual; invalidation contract.
- `usePaginatedQuery` (cursor) vs the offset wrappers (users, api-keys) — RB-5
  tagging accurate.

### Phase 4 — Shell, spaces, dashboard, account
- `(app)/layout` shell + providers (AppContext, JobsProvider); the viewport
  lock for chat.
- `useSpace()` / space aliases (personal/organization) + `can(action, resource)`
  vs tenant `can(requirement)` — used correctly everywhere.
- Nav gating matches Svelte visibility rules; org-space exclusions.
- Account: profile, api-keys, integrations parity.

### Phase 5 — Chat (RB-2 + AI SDK v6)
Unique risks: the widest behavioral surface; the v3 stream.
- `map-session` + the three chunk-filter layers (the memory's
  project_sse_chunk_filter_layers note) — nothing silently dropped.
- AI SDK v6 transport, held-stream tool approval (data-tool-approval
  reconcile), attachments (same-file reselect #491), abort mid-stream.
- Mentions redesign + group-chat single-target behavior; history panel;
  `window.history.replaceState` (not router.replace) rationale holds.
- Streamdown `@source` globs present; model selector shows model details (#493).

### Phase 6 — Builders + knowledge
Unique risks: per-section-save redesign; jobs/upload plumbing.
- Per-section save vs the Svelte global draft/diff editor — no lost-update or
  stale-field bugs; "smarter now" check: is per-section actually better UX, and
  is there hidden duplication across the editor sections?
- Jobs poller: adaptive interval, `JOB_INVALIDATION_KEYS` breadth, upload queue
  (max 5, XHR progress) — leaks/races.
- Knowledge picker pure modules (logic.ts/selection.ts/grouping.ts) — tests
  cover the bucketing/dedup rules; re-verify against Svelte semantics.
- Apps run inputs: the condensed audio-recorder vs the 742-line Svelte one —
  what hardening did we drop (stall detection, device-disconnect, diagnostics)?
  Decide accept vs restore. File-upload rules from input fields.
- Services POST-as-update; app PATCH; RB-5 inventory accurate.

### Phase 7 — Admin
Unique risks: security gating + the cookie spike + many CRUD surfaces + the
generous deferrals.
- **Audit access-session cookie spike** — deepest review: the proxy re-scope
  (path rewrite, Domain strip, Secure/SameSite over the real origin), only
  `audit_session_id` forwarded, behaviour when backend `testing` flag differs.
  This is the riskiest single change in Phase 7.
- Server-side admin gate on `/admin/layout` + nav gating; every mutation
  invalidates the right keys.
- Governance policy `toUpdate()` preserve-the-allow-list logic — confirm a
  toggle never wipes models/servers/tools (S0 if wrong — it's a security
  policy write).
- Models flags endpoint (`*UpdateFlags`) vs tenantModels — the everyday flags
  go through the simple endpoint; confirm no field is silently dropped.
- Each deferral in PARITY.md: is it truly out of scope, or a hidden S1?

### Phase 8 — i18n / polish / parity / prod
- i18n parity (verified 3609/3609) + dead-key scan + no hardcoded text.
- error/not-found/loading coverage per area (only `(app)` has them — do other
  groups need their own?).
- Dockerfile: actually `docker build` it; standalone paths; healthz in-container.
- Headers; CSP plan; PARITY.md accuracy (every PASS spot-checked, every
  DEFERRED justified); CUTOVER.md realism.

## Findings log

One row per finding. Add as we review; update disposition when resolved.

| # | Phase | Sev | Finding | Disposition |
|---|---|---|---|---|
| 1.1 | 1 | S2 parity | No per-page browser `<title>`. Root metadata is static `title: "Eneo"`; the Svelte app set `Eneo.ai – {space} – {page}` per route, so tabs/history/bookmarks lose context. | **defer → Phase 8** (cross-cutting; fix = root `title.template` + `generateMetadata`/`metadata` on key routes) |
| 1.2 | 1 | S3 robustness | No `app/global-error.tsx`: an error in the root layout/providers has no styled boundary (falls back to Next's default white page). | **FIXED** — added `global-error.tsx` (self-contained, dependency-free) |
| 1.3 | 1 | S4 note | Two distinct concepts named "proxy": `src/proxy.ts` (Next 16 middleware — auth gating/refresh) vs `app/api/eneo/[...path]/route.ts` (REST proxy). Confusing on onboarding; the middleware filename is mandated by Next 16, so only documentable. | **accept/note** |
| 1.4 | 1 | S3 maintainability | Query-options were inline in the governance / prompt-library / insights admin pages, not in a `feature.ts` module like the rest. | **FIXED** — extracted to `governance.ts` / `prompt-library.ts` / `insights.ts` |

| 2.1 | 2 | **S1 security** | Open redirect after login: both the OIDC callback (`auth/callback`) and the password action used `next.startsWith("/")`, which accepts `//evil.com` / `/\evil.com` (protocol-relative) — `new URL("//evil.com", origin)` resolves to another origin. A crafted `?next=` could redirect a freshly-logged-in user off-site. | **FIXED** — shared `safeNextPath()` (rejects `//` and `/\`) + unit test; wired into both sinks |

### Phase 2 verdict — reviewed, one security fix

Auth is otherwise well-built and uses the right tools rather than hand-rolling:
**`openid-client` v6** for OIDC (PKCE S256 + state + nonce, validated in
`authorizationCodeGrant`; ID-token validation handled by the library; discovery
cached with TTL; RP-initiated logout). Session is a **JWE** (`jose`, dir +
A256GCM, SHA-256-derived key, zod-validated on open, tamper/expiry → null); the
PKCE transaction gets the same encrypted-cookie treatment. Cookie flags correct
(`httpOnly`, `secure` in prod, `sameSite=lax`, `path=/`, per-mode maxAge).
Sliding OIDC refresh in `proxy.ts` with the RSC-can't-write-cookies caveat
documented and handled. Password mode decodes the backend JWT only for exp/sub
(the backend re-validates every call — correct; the frontend never authorizes).
The single issue was the open redirect (2.1), now fixed.

### Phase 1 verdict — reviewed, near-clean

Foundation is in strong shape; **no S0/S1**. Confirmed: strict tsconfig incl.
`noUncheckedIndexedAccess`; **0** `as any`, **0** `@ts-expect-error`, **0**
`TODO/FIXME`; eslint = next core-web-vitals + ts with scoped relaxations only
for vendored `ai-elements`; every `eslint-disable` justified inline (proxied
`<img>`, mount-only listeners); both `console.*` are error-boundary logs; the
one raw hex is the brand colour in the logo SVG; `env.ts` ↔ `.env.example` ↔
`ENV.md` agree; root layout i18n-correct (`lang={locale}`), next-themes drives
an **active** `.dark` variant (web-next has dark mode, unlike the Svelte app);
Query follows the TanStack SSR per-request-client pattern; devtools no-op in
prod; `src/proxy.ts` is the sole Next-16 middleware (no stray `middleware.ts`).
Open items above are S2–S4 only.
