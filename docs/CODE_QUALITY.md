# Code quality & dead-code tooling

This repo aims to give both humans and AI assistants a **clear, machine-readable
signal** of what is wrong or unused. Tooling is split into two tiers:

- **Enforced gates** — block commits / CI. Must always pass.
- **Advisory analysis** — surfaces candidates for a human to triage. Never
  auto-removes anything, never blocks a commit.

Everything is runnable from the repo root via [Task](https://taskfile.dev):

```bash
task check      # all enforced gates (backend + frontend)
task deadcode   # all advisory dead-code analysis (backend + frontend)
```

## Enforced gates

| Area     | Tool                          | Command                          |
| -------- | ----------------------------- | -------------------------------- |
| Backend  | ruff (lint `F,E9,I`)          | `task check:backend`             |
| Backend  | ruff-format                   | (included above)                 |
| Backend  | pyright (ratcheting baseline) | pre-commit / `typecheck`         |
| Frontend | svelte-check (types)          | `task check:frontend`            |
| Frontend | eslint (incl. unused vars)    | (included above)                 |
| Frontend | prettier                      | pre-commit                       |

> Unused **imports / locals / parameters** are already caught as errors:
> ruff `F` on the backend, `@typescript-eslint/no-unused-vars` on the frontend
> (prefix an intentionally-unused symbol with `_`). The advisory tools below
> cover what those *cannot* see — whole unused files, exports, dependencies and
> dead functions/classes.

## Advisory dead-code analysis

Run with `task deadcode` (or the per-area tasks). All three are intentionally
**not** in pre-commit: they need human judgement and have known false positives.

### Frontend — Knip

[Knip](https://knip.dev) finds unused **files, exports, exported types, and
dependencies** across the bun workspace. Config: `frontend/knip.json`.

```bash
cd frontend
bun run knip
```

Known-noise that is configured away: generated paraglide i18n
(`**/paraglide/**`), the `@intric/icons/*` virtual module (vite plugin), the
build-time icon template `packages/ui/src/icons/Icon.svelte`, the SvelteKit
`hooks.ts` reroute entry, the `apps/docs-site` workspace (separate Next/Nextra
toolchain), and `tests/**`. `openapi-typescript` is invoked via `bun x` in
`intric-js/update.js`, so it is ignored there too.

The `exports`/`types` rules are turned **off** (`rules` in `knip.json`): in this
component-heavy app they are dominated by barrel / compound-component re-exports
(e.g. `<AlertDialog.Root>`), which are intentional API surface rather than dead
code. Knip is therefore used as a high-signal **files + dependencies** detector.
Flip those rules back on temporarily if you want to audit exports.

### Backend — Vulture

[Vulture](https://github.com/jendrikseipp/vulture) finds dead Python symbols
(functions, classes, variables, unreachable branches) — the layer ruff's `F`
rules don't reach. Config: `[tool.vulture]` in `backend/pyproject.toml`
(`min_confidence = 80`, scans `src/intric`).

```bash
cd backend
uv run vulture                       # uses pyproject config
uv run vulture --min-confidence 100  # only certain findings
```

Known false positives are listed in `ignore_names` in `[tool.vulture]`: dunder
protocol params (`__aexit__`'s `exc_val`/`exc_tb`), Protocol-signature params,
and imports referenced only in string / `from __future__ import annotations`
type hints (which ruff `F401` already validates). Add to that list when a new,
verified false positive appears. `base_adapter.py` is `exclude`d (it keeps an
intentional `if False: yield` typing shim that vulture cannot ignore by name).

### Backend — deptry

[deptry](https://deptry.com) checks `pyproject.toml` dependencies against actual
imports. Config: `[tool.deptry]` in `backend/pyproject.toml`.

```bash
cd backend
uv run deptry src
```

Codes: `DEP001` missing, `DEP002` declared-but-unused, `DEP003` transitive,
`DEP004` misplaced. Genuinely unused declarations were removed; what remains in
`per_rule_ignores` is deps that are real but invisible to import analysis —
runtime-only packages (DB drivers, server, migrations CLI, env loaders, async
glue), plugin/CLI-resolved ones (`python-calamine`, `tiktoken`), the
not-yet-wired `sentry-sdk`, and the directly-used-but-transitive `sqlalchemy`
family. `example_mcp_server.py` is excluded (standalone `fastmcp` sample).

## Not yet enabled — future ratcheting

Broadening the ruff ruleset (`B`, `ARG`, `SIM`, `UP`, `RUF`, …) currently
surfaces ~2900 findings (~2400 auto-fixable). That is a large cross-cutting
change and is intentionally deferred to its own ratcheted rollout (mirroring the
pyright hardening approach) rather than a drive-by, to keep diffs reviewable and
avoid churning unrelated history. `ARG` (unused arguments) is the most
dead-code-relevant addition when that happens.
