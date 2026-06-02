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

First run on a fresh machine needs the Chromium binary for component tests:

```bash
cd frontend && bun x playwright install chromium chromium-headless-shell
```

### End-to-end

E2E needs the **full stack reachable** (backend + database) and builds a
production preview of the app on port `4173`.

```bash
cd apps/web && bun run test:e2e            # build + preview + run
cd apps/web && bun run test:e2e --ui       # interactive runner
cd apps/web && bun run test:e2e --list     # discover tests without starting the server
```

> ⚠️ **Do not run E2E while `bun run dev` is live.** The E2E web server runs
> `vite build`, which writes to the shared `.svelte-kit` output and corrupts the
> running dev server. Stop dev first, or start your own preview and let
> `reuseExistingServer` pick it up.

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
See `tests/smoke.spec.ts` for the reference example:

```ts
import { expect, test } from "@playwright/test";

test("unauthenticated visitor lands on the login page", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page).toHaveTitle(/Eneo\.ai/);
});
```

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

The `Frontend` job in `.github/workflows/ci.yml` runs the **unit + component**
layer on every PR: it installs the Chromium browser, then runs
`bun run --filter @intric/web test:unit`.

E2E is intentionally **not** in the default gate — it needs the full backend +
database stack and is slower/flakier. Run it locally for now; wiring it into CI is
a follow-up that requires standing up the stack and auth fixtures in the workflow.

## Gotchas / maintenance

- **Keep `vitest` and `@vitest/browser` on the exact same version.** A mismatch
  triggers a "Running mixed versions" warning and can cause subtle bugs. They are
  currently pinned together at `3.2.4`.
- **`playwright` is pinned to match `@playwright/test` (`1.58.2`).** Vitest browser
  mode imports the `playwright` package; if its version drifts from the installed
  browser build you get "Executable doesn't exist" — fix by reinstalling browsers
  with the workspace-local Playwright (`./node_modules/.bin/playwright install`).
- Component tests need the Chromium binary present; CI installs it explicitly.
- The two Vitest projects are configured in `apps/web/vite.config.ts` under
  `test.projects`. The `server` project excludes `*.svelte.test.ts`; the `client`
  project includes only those.
