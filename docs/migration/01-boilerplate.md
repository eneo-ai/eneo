# Phase 1 — Boilerplate: Next.js app skeleton + shared component library

## Goal
A bootable, CI-green Next.js 16 App Router app at `frontend/apps/web-next` plus a shared React component library at `frontend/packages/ui-react` (`@intric/ui-react`) holding all shadcn/ui primitives, themed with a fresh shadcn palette that carries over ONLY the Eneo accent color. TypeScript strict, next-intl scaffolding (sv + en), base layout, env handling, lint/format/test wiring, and a health endpoint.

Standing rule established here for all later phases: every piece of UI is composed from shadcn/ui (and, from Phase 5, AI Elements) primitives living in `@intric/ui-react`. Missing primitives are installed into the package via the shadcn CLI; generic composites (data-table, form field, page header, confirm dialog, empty state, …) are added to the package as they emerge; apps never define their own primitives. No auth, no backend calls yet (except an optional unauthenticated `/version` smoke call).

## Prerequisites
- Devcontainer running (`eneo_devcontainer-eneo-1`), Bun available at `/home/vscode/.bun/bin/bun`.
- Node ≥ 20.9 inside the container (Next 16 requirement); verify, the container currently targets Node 20.
- Read `docs/migration/00-overview.md` §3 (target architecture) first.

## Versions to install (verified 2026-06-11; re-verify minors at execution time, do not jump majors)
- `next` 16.2.x, `react` / `react-dom` 19.2.x, `typescript` ^5.x (≥5.1)
- `tailwindcss` ^4.3 via `@tailwindcss/postcss` (or the Vite plugin is N/A here; Next uses PostCSS)
- shadcn CLI: `npx shadcn@latest` (4.x), style: new-york, CSS variables mode
- `next-intl` latest, `next-themes` latest, `zod` ^4
- ESLint 9 flat config (`eslint.config.mjs`) + `@next/eslint-plugin-next` + prettier (match repo prettier config incl. `prettier-plugin-tailwindcss`)
- `vitest` ^3 + `@testing-library/react` for unit/component tests
- Do NOT install `ai` / `ai-elements` yet (Phase 5).

## Scope
**In**: app scaffold, the `@intric/ui-react` workspace package with shadcn monorepo wiring, fresh theme + dark mode (Eneo accent only carried over), base layout (header placeholder, sidebar placeholder, content area), i18n plumbing with ~20 seed messages, env module, `/healthz`, lint/format/typecheck/test scripts, CI job, dev port that does not collide with the SvelteKit app.
**Out**: auth, API client, any real feature route, AI Elements (Phase 5 installs them into the same package), Dockerfile hardening (Phase 8), porting the full 3,383-key message catalogs (script lands here, full port is ongoing), porting the Svelte app's OKLCH token set (explicitly not done; see step 4).

## Step-by-step
1. **Scaffold**: from `/workspace/frontend`, run `bunx create-next-app@latest apps/web-next` with: TypeScript, ESLint, Tailwind, `src/` dir, App Router, `@/*` alias, Turbopack default. Then align `package.json` name to `@intric/web-next` and add it to the Bun workspace (root `frontend/package.json` workspaces already globs `apps/*`; verify).
2. **TS strict**: enable `strict`, `noUncheckedIndexedAccess` in `tsconfig.json`.
3. **Dev port**: set dev script to `next dev -p 3100` (SvelteKit owns 3000). Production stays 3000 inside its own container later.
4. **Shared component library + shadcn init**: create `frontend/packages/ui-react` (`@intric/ui-react`) and wire it per the shadcn monorepo guide (verify against ui.shadcn.com/docs/monorepo at execution time): `components.json` in both the package and the app, with the CLI run from the app installing primitives into the package under the `@intric/ui-react` import alias. Style: new-york, CSS variables mode, a neutral base (zinc or neutral, pick whichever reads best with the accent). Theme: a fresh, cohesive shadcn palette. The ONLY value carried over from the old design system is the Eneo accent color: read `accent-default` (and its on-fill/foreground pair) from `frontend/packages/ui/src/styles/` and map it to shadcn `--primary`/`--primary-foreground` (light and dark). Do NOT transcribe the rest of the Svelte token mapping; backgrounds, borders, muted tones, destructive, charts, etc. come from the stock shadcn palette tuned for cohesion with the accent. Install the initial primitive set the shell needs (button, dropdown-menu, avatar, sonner, skeleton, tooltip).
5. **Dark mode**: `next-themes` provider in root layout (`attribute="class"`, `defaultTheme="system"`, `enableSystem`, `suppressHydrationWarning` on `<html>`). Dark values are the stock shadcn dark palette plus the accent's dark-mode variant; nothing ported from the Svelte `[data-theme="dark"]` block.
6. **i18n**: install next-intl (without i18n routing; locale from cookie, matching today's behavior where locale is a persisted preference, not a URL segment). Create `src/lib/i18n/` with `request.ts` (cookie → locale, default `sv`) and `messages/{sv,en}.json` seeded with ~20 keys needed by the shell. Write `scripts/convert-paraglide-messages.mjs` that converts `frontend/apps/web/messages/{sv,en}.json` (flat Paraglide format) to next-intl JSON, flagging non-ICU interpolations for manual review. Run it once and commit the output; later phases re-run it as they port routes.
7. **Base layout**: root layout = theme + intl + (later) query providers; `(public)` and `(app)` route groups; `(app)/layout.tsx` renders a header with app name, theme switcher, and a placeholder profile area; an empty `(app)/dashboard/page.tsx` rendering a translated heading.
8. **Env module**: `src/lib/env.ts` validating server env with zod at import time: `ENEO_BACKEND_URL` (required), `SESSION_SECRET` (required from Phase 2, optional now), feature flags `SHOW_WEB_SEARCH`, `SHOW_HELP_CENTER`, `HELP_CENTER_URL`, `REQUEST_INTEGRATION_FORM_URL`. No `NEXT_PUBLIC_*` backend URL: the browser never calls the backend directly in this architecture. Add `.env.example`.
9. **Health endpoint**: `src/app/(public)/healthz/route.ts` returning `{status:"OK", timestamp, service:"frontend-web-next"}` (same shape as the Svelte app's).
10. **Lint/format/test**: `eslint.config.mjs` (flat, ESLint 9) with `@next/eslint-plugin-next` recommended + repo-consistent rules; reuse the root prettier config. `vitest.config.ts` (jsdom) + one component test (theme switcher renders) + one unit test (env validation rejects missing `ENEO_BACKEND_URL`). Scripts: `dev`, `build`, `start`, `lint`, `check` (tsc --noEmit), `test`.
11. **CI**: extend `.github/workflows/ci.yml` with a `web-next` job mirroring the web job: install, `lint`, `check`, `test`, `build` (Turbopack). Do not gate the existing web jobs on it.

## Files/structure created
```
frontend/packages/ui-react/
├─ src/components/ui/…            (shadcn CLI-installed primitives)
├─ src/styles/globals.css         (Tailwind v4 @theme: fresh palette + Eneo accent)
├─ components.json
└─ package.json                   (@intric/ui-react)

frontend/apps/web-next/
├─ src/app/{layout.tsx, globals.css → imports @intric/ui-react styles}
├─ src/app/(public)/healthz/route.ts
├─ src/app/(app)/{layout.tsx, dashboard/page.tsx}
├─ src/components/shell/{header.tsx, theme-switcher.tsx}   (compositions, not primitives)
├─ src/lib/{env.ts, i18n/request.ts}
├─ src/lib/i18n/messages/{sv,en}.json
├─ scripts/convert-paraglide-messages.mjs
├─ components.json                (CLI target config → installs into the package)
├─ eslint.config.mjs, vitest.config.ts, tsconfig.json, postcss.config.mjs
├─ .env.example
└─ package.json
```

## VALIDATION GATE
All run via docker exec (pattern: `docker exec -u vscode eneo_devcontainer-eneo-1 bash -i -c "cd /workspace/frontend/apps/web-next && /home/vscode/.bun/bin/bun run <script>"`).
1. `bun install` at `/workspace/frontend` — exits 0, lockfile updated, existing `apps/web` still builds (`bun run build` in apps/web unaffected).
2. `bun run check` — 0 TypeScript errors.
3. `bun run lint` — 0 errors.
4. `bun run test` — both tests pass.
5. `bun run build` — production build succeeds (Turbopack).
6. `bun run dev` then `curl -s http://localhost:3100/healthz` → `{"status":"OK",...}`; `curl -s http://localhost:3100/dashboard` → 200 with the Swedish heading.
7. Manual: open `http://localhost:3100/dashboard`, toggle dark mode, no flash-of-wrong-theme on reload; switch locale cookie to `en` and see English. Buttons/links render in the Eneo accent in both light and dark; everything else is the stock shadcn palette.
8. `bunx shadcn@latest add dialog` (run from the app) lands the component in `packages/ui-react/src/components/ui/` and it imports cleanly from `@intric/ui-react` (prove the monorepo wiring; keep the component, Phase 4 needs it).
9. CI: the new job passes on the PR.

## Exit criteria
Gate green; SvelteKit app untouched and still running on 3000; conversion script committed with first-pass converted catalogs (build does not depend on full catalog correctness).

## Risks / unknowns
- Bun + Next 16 dev-server quirks inside the devcontainer (file watching may need polling like the Vite setup). Mitigation: `WATCHPACK_POLLING=true` if HMR is flaky.
- shadcn CLI monorepo wiring with Bun workspaces (the guide assumes pnpm/turbo in places); if the CLI misplaces files, fix `components.json` aliases rather than moving files by hand, so future `add` commands keep landing in the package.
- The accent color alone may clash with stock neutrals in edge surfaces (focus rings, charts); allow small accent-derived adjustments (ring, chart-1) but document every token that deviates from stock in a comment block at the top of `globals.css`.
- Paraglide → ICU conversion edge cases (parameterized messages). The script flags them; do not bulk-fix in this phase.
