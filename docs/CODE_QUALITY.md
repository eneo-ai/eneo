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
bun run knip            # full report
bun run knip:strict     # only high-confidence: files, deps, unlisted
```

Known-noise that is configured away: generated paraglide i18n
(`**/paraglide/**`), the `@intric/icons/*` virtual module (vite plugin), the
`apps/docs-site` workspace (separate Next/Nextra toolchain), and `tests/**`.

The `Unused exports` category is large for `packages/ui` (a component library
exposes a public API not all consumed internally) — treat it as a browsing aid,
not a worklist.

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

Known false positives: dunder-protocol params (`__aexit__`'s `exc_val`/`exc_tb`)
and symbols referenced only inside `TYPE_CHECKING` / string annotations. Triage
before deleting; add survivors to a whitelist if they recur.

### Backend — deptry

[deptry](https://deptry.com) checks `pyproject.toml` dependencies against actual
imports. Config: `[tool.deptry]` in `backend/pyproject.toml`.

```bash
cd backend
uv run deptry src
```

Codes: `DEP001` missing, `DEP002` declared-but-unused, `DEP003` transitive,
`DEP004` misplaced. Runtime-only deps (DB drivers, server, migrations CLI, env
loaders, async glue) and the directly-used-but-transitive `sqlalchemy` family
are pre-ignored in config so the remaining list is actionable.

## Not yet enabled — future ratcheting

Broadening the ruff ruleset (`B`, `ARG`, `SIM`, `UP`, `RUF`, …) currently
surfaces ~2900 findings (~2400 auto-fixable). That is a large cross-cutting
change and is intentionally deferred to its own ratcheted rollout (mirroring the
pyright hardening approach) rather than a drive-by, to keep diffs reviewable and
avoid churning unrelated history. `ARG` (unused arguments) is the most
dead-code-relevant addition when that happens.
