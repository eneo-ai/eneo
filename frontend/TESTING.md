# Frontend testing guide

This document describes how the `@intric/web` app is tested, where each kind of
test lives, how to run and write them, and how to lean on AI tooling while doing
so. The stack is the de-facto SvelteKit standard — **Vitest + Playwright** — split
into three layers.

## The three layers

| Layer | Tool | Runs in | File suffix | Use it for |
| --- | --- | --- | --- | --- |
| **Unit** | Vitest (`server` project, Node) | Node | `*.test.ts` | Pure functions: formatters, parsers, diffing, business logic. Fast, no DOM. |
| **Component** | Vitest browser mode (`client` project, real Chromium via Playwright) | Chromium | `*.svelte.test.ts` | A single Svelte component's rendered output and behaviour (props, events, conditional rendering). |
| **End-to-end** | Playwright | Built app + full stack | `tests/*.spec.ts` | Real user flows across pages and the backend (login, send a chat message, admin actions). |

Rule of thumb: **push tests down**. If logic can be a pure function, unit-test it.
If it's component rendering, component-test it. Reserve E2E for flows that only
make sense against the real, running system — those are the slowest and most
expensive to maintain, so keep them few and high-value.

Why component tests run in a real browser and not jsdom: Svelte 5 runes, `$effect`,
and transitions don't behave correctly under jsdom. Vitest browser mode renders in
headless Chromium (driven by Playwright), which is both correct and the path the
Svelte team now recommends.

## Running the tests

All commands run from `frontend/` (or `frontend/apps/web/`).

**Run everything with one command.** From `frontend/apps/web`:

```bash
bun run test:all   # installs Chromium if missing → unit + component → E2E
```

`test:all` is the low-friction entry point: it ensures the Chromium binary is
present (idempotent — a no-op once installed), runs the Vitest unit + component
layer, then the Playwright E2E suite (which brings its own backend stack up and
down). Needs Docker running for the E2E part. Everything below is the same steps
broken out for when you want to run just one layer.

```bash
# Unit + component (both Vitest projects), one-shot — what CI runs
bun run --filter @intric/web test:unit

# Same, but watch mode for local development
bun run --filter @intric/web test:unit:watch

# Only one project
cd apps/web && bun run vitest run --project server   # unit only
cd apps/web && bun run vitest run --project client   # component only

# A single file
cd apps/web && bun run vitest run src/lib/core/formatting/formatBytes.test.ts
```

`test:all` installs Chromium for you; to do it by hand (e.g. before running only
the component layer):

```bash
cd frontend && bun x playwright install chromium chromium-headless-shell
```

### End-to-end

E2E runs the built app against an **isolated test backend** — never your dev or
prod stack. The stack (`docker-compose.e2e.yml` at the repo root) is prod-safe by
construction:

- it brings its **own throwaway postgres + redis** (in-memory, no volumes), so it
  never touches your dev/prod database and your local db can be in any state;
- every outbound model key is overridden with a dummy, so it can't reach a real
  LLM provider even if a flow tries to;
- it reuses the already-built devcontainer image, so it ships nothing into any
  production image.

The stack is **ephemeral and managed for you**: `bun run test:e2e` brings up its
own throwaway postgres + redis + backend (seeded fresh), runs the suite, then
removes everything. Each run starts from a clean, known database.

```bash
cd frontend/apps/web && bun run test:e2e          # up → seed → run → down
cd frontend/apps/web && bun run test:e2e --ui     # interactive runner
cd frontend/apps/web && bun run test:e2e --list   # discover tests, no stack

# Iterating on specs? Manage the stack yourself and skip up/down each run:
docker compose -f docker-compose.e2e.yml up -d --wait
E2E_MANAGE_STACK=0 bun run test:e2e
docker compose -f docker-compose.e2e.yml down
```

The suite authenticates once (`auth.setup.ts` logs in the seeded user and saves a
session to `playwright/.auth/`), then every spec reuses that session — login is
exercised for real, but each test starts authenticated.

**Runs alongside `vite dev`.** The E2E web server runs `vite build` + `preview`,
but into a *separate* SvelteKit output dir (`SVELTE_KIT_OUT_DIR=.svelte-kit-e2e`,
set in `playwright.config.ts` and honoured by `svelte.config.js`). It never writes
the `.svelte-kit` your dev server uses, so you can keep developing while the suite
runs — no more blank-page corruption, no need to stop dev first. The seeded login
is `e2e@example.com` / `E2ePassword1!` in tenant `E2ETenant`.

**Deterministic chat.** The stack includes a tiny OpenAI-compatible **mock model
server** (`e2e/mock_model_server.py`); `e2e/seed.py` seeds a default completion
model whose provider `endpoint` points at it, so chat completions return a fixed
string (`E2E mock completion: pong`) — fast, free, and identical every run. No
real provider is ever called. To keep credentials simple the stack runs with
encryption off, so the seeded api-key is plaintext (and meaningless).

> **Status:** the full suite (login, unauthenticated redirect, authenticated
> landing, and the deterministic chat stream) runs green in CI on every PR via the
> `Frontend E2E` job, and locally with `bun run test:all` (or `bun run test:e2e`).

## Writing tests

### Unit test (`*.test.ts`)

Plain Vitest. Import the function, assert on its output.

```ts
import { expect, test } from "vitest";
import { formatBytes } from "./formatBytes";

test("formats kilobytes", () => {
  expect(formatBytes(1024)).toEqual("1 KB");
});
```

### Component test (`*.svelte.test.ts`)

The `.svelte.test.ts` suffix is what routes the file to the browser-mode `client`
project — don't use a plain `.test.ts` for component tests. Render with
`vitest-browser-svelte`, locate elements with `page`, assert with `expect.element`.

See `src/lib/components/ui/badge/badge.svelte.test.ts` for the reference example:

```ts
import { createRawSnippet } from "svelte";
import { describe, expect, it } from "vitest";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { Badge } from "./index.js";

describe("Badge", () => {
  it("renders its content", async () => {
    render(Badge, {
      // Passing snippet children from a test requires createRawSnippet.
      children: createRawSnippet(() => ({ render: () => `<span>Active</span>` }))
    });
    await expect.element(page.getByText("Active")).toBeVisible();
  });
});
```

Notes:
- `render` auto-cleans between tests — no manual teardown.
- Prefer accessible locators (`getByRole`, `getByText`, `getByLabelText`) over CSS
  selectors; they double as accessibility checks.
- `expect.element(...)` retries until the assertion passes or times out, so you
  rarely need manual waits.
- Components that render human-facing text use Paraglide `m.*` messages. Those
  compile during the test build, so assert against the rendered English string (or
  query by role/structure to stay language-agnostic).

### E2E test (`tests/*.spec.ts`)

Standard Playwright. `baseURL` is preconfigured, so navigate with relative paths.
Specs run in the `chromium` project, which **starts already authenticated** via the
session saved by `auth.setup.ts` — so just navigate into the app. The reference
specs:

- `tests/auth.setup.ts` — logs in through the real UI and persists the session.
- `tests/authenticated.spec.ts` — a logged-in user reaches the chat workspace.
- `tests/smoke.spec.ts` — an anonymous visitor is redirected to login (opts out of
  the shared session with `test.use({ storageState: { cookies: [], origins: [] } })`).

```ts
import { expect, test } from "@playwright/test";

test("authenticated user lands in the personal chat workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/spaces\/personal\/chat/);
  await expect(page.getByRole("navigation").first()).toBeVisible();
});
```

Prefer stable, language-agnostic locators (`input[name="email"]`,
`button[type="submit"]`, `getByRole`) over text — the UI is localized via
Paraglide `m.*`.

## AI-assisted workflow

This setup is chosen partly because it has the strongest AI tooling story.

**Component & unit tests — let the model write them.** Vitest is ubiquitous in
training data, so Claude/Copilot generate accurate tests and self-correct from the
clear failure output. A good prompt: _"Write a `*.svelte.test.ts` for
`X.svelte` using vitest-browser-svelte and `page` locators; cover the empty,
loading, and populated states."_ Then run `test:unit:watch` and let it iterate.

**E2E — drive a real browser with Playwright MCP.** The Playwright MCP server lets
an agent open the app, read the accessibility tree, click through a flow, and write
the resulting `*.spec.ts` — far more reliable than guessing selectors. Two ways in:

- Ask the agent to perform the flow through the Playwright MCP tools, then save it
  as a spec.
- Or use Playwright's own codegen to record interactively:
  ```bash
  cd apps/web && bun x playwright codegen http://localhost:4173
  ```

When generating selectors, prefer role/text/label locators (stable) over nth-child
CSS paths (brittle).

## CI

Two jobs in `.github/workflows/ci.yml` run on every PR:

- **`Frontend`** runs the **unit + component** layer: installs the Chromium
  browser, then runs `bun run --filter @intric/web test:coverage` (tests +
  coverage). This job **is** part of the aggregate `CI` gate, so a failure blocks
  the PR.
- **`Frontend E2E`** stands up the isolated stack (`docker-compose.e2e.ci.yml`,
  backend built from its Dockerfile) and runs the full Playwright suite, uploading
  the HTML report as an artifact.

**`Frontend E2E` is currently non-blocking:** it is *not* in the aggregate `CI`
job's `needs:` list, so a red E2E run does not fail the PR (it adds real CI time —
backend image build + frontend build + browser run — and the suite is newer/more
prone to flake). To make it blocking, add the `Frontend E2E` check to branch
protection in repo settings.

## Coverage

Coverage comes from the **Vitest** layer only (unit + component) — it maps cleanly
back to source. E2E is deliberately excluded: Playwright measures the bundled
build, which maps back to Svelte source poorly. Backend coverage is produced
separately by `pytest-cov`.

```bash
cd apps/web && bun run test:coverage   # runs the tests + writes coverage/
```

This writes `apps/web/coverage/`: `index.html` (browse locally), `lcov.info` and
`coverage-summary.json` (for tooling). Config lives in `vite.config.ts` under
`test.coverage` (v8 provider; generated i18n and `*.d.ts`/test files excluded).
The number is **near-zero today** — there are barely any tests yet. That's the
point: it's a baseline to grow from, not a vanity metric.

### Whole-system report — "where is the code untested?"

To see frontend **and** backend coverage in one go — and a ranked list of the
least-covered files so gaps jump out — run the repo-root script:

```bash
scripts/coverage.sh             # frontend + backend UNIT tests (fast, ~2 min)
scripts/coverage.sh --full      # also run backend INTEGRATION tests (accurate, slower)
scripts/coverage.sh --frontend  # frontend only (~11 s)
scripts/coverage.sh --backend   # backend only
scripts/coverage.sh --help
```

It runs the frontend suite on the host and the backend suite inside the
devcontainer (`eneo_devcontainer-eneo-1`, started automatically by your dev
setup), then prints the completely-untested and least-covered files per side and
points at the clickable HTML reports (red lines = untested):

- frontend: `frontend/apps/web/coverage/index.html`
- backend: `backend/htmlcov/index.html` (plus `backend/coverage.json`)

**Accuracy caveat:** coverage only reflects the tests you run. In the default fast
mode the backend integration suite is skipped, so code exercised *only* by
integration tests shows up as a gap (a false negative). Use `--full` for the
picture you can trust — it needs the Docker socket and runs as root in the
container (the testcontainers requirement).

These reports are large (~36 MB frontend + ~42 MB backend) and regenerated every
run, so they're **gitignored — never commit them**. CI keeps the last run's HTML
as a downloadable artifact (below); for a tracked "what was it last time" number,
commit a small summary, not the HTML.

**Two kinds of report in CI (both report-only, neither gates the PR):**

- **Whole-project** — the `Frontend` job uploads the Vitest coverage as the
  `frontend-coverage` artifact; the `Backend tests` job uploads `pytest-cov`'s
  `coverage.xml` + `htmlcov` as `backend-coverage`. Download from the run page.
- **Patch coverage** — the `Coverage diff` job runs [`diff-cover`] against the PR's
  base branch and reports how well tests cover **the lines this PR changed**,
  frontend and backend separately. It posts/updates a sticky PR comment and writes
  the same report to the job summary. This is the PR-relevant signal ("did new
  code arrive untested?"). It is **not** in the aggregate `CI` gate, so it never
  blocks — set a `--fail-under` threshold later to make it enforcing.

> Note: `diff-cover` matches coverage paths against git paths, which are
> repo-root-relative. The reports use package-relative paths (`src/…` for lcov,
> `src/intric/…` in the cobertura xml), so the `Coverage diff` job rewrites them to
> repo-root-relative before running. If you move the coverage output, keep that
> rewrite in sync or patch coverage silently reports "no lines".

## Gotchas / maintenance

- **Keep `vitest`, `@vitest/browser` and `@vitest/coverage-v8` on the exact same
  version.** A mismatch triggers a "Running mixed versions" warning and can cause
  subtle bugs. They are currently pinned together at `3.2.4`.
- **`@playwright/test` and `playwright` are both pinned exactly at `1.58.2`** (no
  caret) so they can't drift apart. Vitest browser mode imports the `playwright`
  package; if its version drifts from the installed browser build you get
  "Executable doesn't exist" — fix by reinstalling browsers with the
  workspace-local Playwright (`./node_modules/.bin/playwright install`). CI installs
  the browser with the same pinned version (`bun x playwright@1.58.2 install`).
- Component tests need the Chromium binary present; CI installs it explicitly.
- The two Vitest projects are configured in `apps/web/vite.config.ts` under
  `test.projects`. The `server` project excludes `*.svelte.test.ts`; the `client`
  project includes only those.
