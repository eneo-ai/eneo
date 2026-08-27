# Eneo Frontend

Multirepo containing:

- The Eneo Web GUI, a SvelteKit app in `/apps/web`
- The Eneo.js API client, a plain JS client wrapping all Eneo endpoints used in the Web GUI in `packages/eneo.js`
- The Eneo UI Library, offering reusable Svelte components for our frontend applications in `packages/ui`

## Setup

### Installing

```bash
bun -w run setup
```

Will install all required dependencies. Have a look at the README files in the respective subfolders for further instructions.

### Local dev server

If you want to develop the Web GUI while also working on the UI library at the same time, run

```bash
bun run dev
```

This is the canonical frontend start command. It starts both the UI package watcher and the
web app on the fixed development URL `http://localhost:3000`.

The command is safe to run more than once: it reports an existing Eneo frontend instead of
trying to start a second Vite server. Use the lifecycle commands when a previous terminal was
closed without stopping the server:

```bash
bun run dev:status   # Show whether this checkout owns the local frontend
bun run dev:restart  # Safely stop this checkout's frontend and start a clean instance
bun run dev:stop     # Stop this checkout's frontend
```

The stop and restart commands only signal a Vite process that is verified to belong to this
checkout. If another application owns port 3000, they report the conflict and leave it running.
Production build and runtime commands do not use this development lifecycle.

### Formatting & Linting

Prettier is configured for this project, you can format your code before committing either through a format action in your code editor, or by running:

```bash
bun run format
```

The same goes for linting, you can run it via

```bash
bun run lint
```

__Hint:__ The linter will also check formatting, so it makes sense to first format your code befor running the linter.

### Testing

The stack is **Vitest** (unit + component) and **Playwright** (E2E). From this directory:

```bash
bun run test          # unit + component (one-shot)
bun run test:watch    # same, watch mode for local dev
bun run test:e2e      # E2E against an isolated throwaway backend (needs Docker)
bun run test:e2e:ui   # E2E in Playwright's interactive runner
bun run test:all      # everything (installs Chromium if missing)
```

The first run installs the Chromium browser automatically. See [`TESTING.md`](./TESTING.md)
for the full guide — the three test layers, where each kind of test lives, and how to write one.
