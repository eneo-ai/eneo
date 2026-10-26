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

## CI execution and recovery

The [contributor CI contract](../frontend/apps/docs-site/src/content/contributing/security.mdx)
describes which changes require which checks. `.github/scripts/ci-change-scope.mjs`
owns the event policy, changed-file classification, Docker matrix and required-job
plan. `.github/scripts/ci-gate.mjs` verifies actual job results against that plan.
Do not add separate path-selection rules to individual workflow steps.

The first job combines scope detection, branch naming, route metadata, naming
guards and script tests. Expensive jobs start only after it succeeds. Both E2E
suites remain required for backend changes, including the optional Next beta.
Develop publication calls full CI once; there is no second standalone CI run
for that push. Release branch pushes, tags and manual publication keep full
validation. Release bundle identity, attestations, scans and smoke tests are
unchanged.

Frontend jobs use the same pinned Node version as the production Docker images
and one Bun download-cache policy. Playwright still installs its system
dependencies: apt network operations have bounded retries, and the entire
installation has a deadline. Chromium downloads may retry once. Test failures
and OOM failures are not automatically retried. The selected Ubuntu release is
explicit rather than following `ubuntu-latest`.

CI image builds import matching Buildx caches with a two-minute timeout. Only
branch pushes export CI caches: PR/queue caches cannot be shared with later
candidates and would consume upload time and cache storage. CI exports use a
separate `ci-<image>` scope, a two-minute limit and non-fatal cache-export
failures; release publication retains its own cache namespace. The Svelte image installs
workspace dependencies before copying app source, then runs the workspace
prepare hooks. Generated local build/test directories are excluded from its
Docker context.

### Validation

The focused contract tests cover both event types, combined queue candidates,
renames/deletions, missing history, shared inputs, filtered images, and gate
failure/skip semantics. They also ensure that every CI worker is covered by the
aggregate. Run from the repository root:

```bash
node --test --test-concurrency=1 .github/scripts/ci-contract.test.mjs
actionlint .github/workflows/ci.yml
python3 -m unittest discover -s scripts/tests -p test_release_bundle.py
```

On the shared development Mac, run each command through
`python3 /Users/maxeriksson/.codex/scripts/run-guarded.py --seconds 90 --`.
Full builds, full suites, and browser/E2E runs require explicit local execution
approval; use the PR's GitHub Actions runs to validate the complete pipeline.

### Diagnosis and rollback

Use the first job's summary to see the selected jobs and images. An unexpectedly
skipped required job fails `CI`, even if GitHub treats that skipped job as green.
Missing or invalid scope output also fails the aggregate.

Heavy jobs have explicit 20–30 minute limits; repository checks have ten minutes
and the aggregate has five. The Svelte E2E build uploads
`frontend-build-resources` with GNU time's wall time, peak RSS and exit status,
including on build failure. Its Node heap limit remains unchanged. These
measurements help investigate the adapter-node OOM; removing the duplicate
standalone build is not a fix for that underlying memory demand.

Compare runner-minutes per merge, completed merges per hour, and median/p95
runner wait before and after rollout. Separate dependency and workflow
concurrency waits from time actually awaiting an available runner. Ruleset build
concurrency is a separate capacity setting; tune it against observed load after
the workflow changes, without weakening required checks.

If selection is wrong, temporarily make `planCi` return the full scope or revert
the scoping change. Keep the aggregate check required. A full revert restores
the previous triggers, jobs and image build; no persisted application data or
deployment format changes need recovery. Do not bypass the CI gate to unblock
publication.

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
(`**/paraglide/**`), the `@eneo/icons/*` virtual module (vite plugin), the
build-time icon template `packages/ui/src/icons/Icon.svelte`, the SvelteKit
`hooks.ts` reroute entry, the `apps/docs-site` workspace (separate Next/Nextra
toolchain), and `tests/**`. `openapi-typescript` is invoked via `bun x` in
`eneo-js/update.js`, so it is ignored there too.

The `exports`/`types` rules are turned **off** (`rules` in `knip.json`): in this
component-heavy app they are dominated by barrel / compound-component re-exports
(e.g. `<AlertDialog.Root>`), which are intentional API surface rather than dead
code. Knip is therefore used as a high-signal **files + dependencies** detector.
Flip those rules back on temporarily if you want to audit exports.

### Backend — Vulture

[Vulture](https://github.com/jendrikseipp/vulture) finds dead Python symbols
(functions, classes, variables, unreachable branches) — the layer ruff's `F`
rules don't reach. Config: `[tool.vulture]` in `backend/pyproject.toml`
(`min_confidence = 80`, scans `src/eneo`).

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
