# Flows tidy Phase 1 baseline and Builder separation inventory

**Plan:** @.claude/plans/flows-clean-tidy.md  
**PRDs:** @.claude/prds/flows-clean-tidy.md, @.claude/prds/flows-ai-builder-launch.md  
**Reference commit:** `d3858286960c9e28301966242018e674bdb04170`  
**Develop merge-base:** `4c5708010e210dec3ce1fb737ed5a95a3c43a9ed`  
**Captured:** 2026-08-19

This is the immutable before-cut snapshot required by the plan's execution
invariants. Counts are deliberately split between core Flows and Builder so
moving Builder to the stacked branch cannot masquerade as implementation
shrinkage.

## Static baseline

Counts use physical lines in tracked Python, TypeScript, Svelte, and test files.
Core backend source is `backend/src/eneo/flows/**/*.py` excluding
`flows/ai_builder`; Builder backend source is `flows/ai_builder/**/*.py`.
Dedicated Builder tests contain `ai_builder` in their path or `builder` in their
filename. Frontend Builder source contains `ai-builder` or `aiBuilder` in its
path. These rules are intentionally reproducible rather than subjective.

| Surface | Files | LOC |
|---|---:|---:|
| Core Flows backend source | 239 | 76,209 |
| Builder backend source | 133 | 61,851 |
| Core Flows backend tests | 233 | 149,703 |
| Builder backend tests | 134 | 127,288 |
| Builder frontend source and dedicated tests | 65 | 21,480 |
| Core Flow Playwright specs | 2 | 424 |
| Builder Playwright specs | 3 | 1,122 |

The diff from `origin/develop` contains 1,924 files and 76 Alembic revision
files. Ten revisions are Builder-named. The live consolidated Flow table module
declares 22 ORM tables: 19 core and 3 Builder (`BuilderSessions`,
`BuilderSessionFiles`, and `BuilderPlans`). The filename-only migration counts
are inventory aids, not the Phase 5 final-schema manifest.

The Swedish and English catalogs each contain 424 keys whose names include
`ai_builder`, `flow_builder`, or `builder_`. The core cut must remove the same
key set from both catalogs and recompile Paraglide; no generated message output
is counted as authored Builder source.

## Test, duration, and coverage baseline

| Scope | Result | Wall clock | Coverage |
|---|---|---:|---:|
| Core Flows unit suites (`tests/unit/flows` plus legacy Flows tests, Builder ignored) | 3,153 passed, 1 xfailed | 86.786 s | 83.25% core-only line + branch coverage |
| Builder backend unit suite | 3,816 passed | 141.213 s | 90% line + branch coverage |
| Builder capability goldens | 151 passed | 5.301 s | Included in Builder coverage |
| Manual consumer golden integration journey | 1 passed | 17.016 s | Integration behavior, not a coverage run |
| Builder frontend focused unit suite | 301 passed in 19 files | 18.826 s | 92.30% statements, 85.67% branches |
| Manual + Builder focused Playwright specs | Not collected | Preview startup exceeded 180 s | Not available |
| Fresh testcontainer database upgrade to Alembic head | Passed as golden-journey session setup | Included in 17.016 s | Schema bootstrap, not a coverage run |
| Critical Builder backend mutation baseline | 311 killed, 144 survived, 18 uncovered (473 total) | 18.9 s mutant execution | 68.4% of tested mutants killed |

The manual golden journey initially exposed two devcontainer defects:
`ENEO_TEST_DOCKER_NETWORK` was absent in the already-running container and the
`vscode` user could not open `/var/run/docker.sock`. The startup fix now joins
the socket's actual numeric group instead of assuming the pre-existing
`docker` group owns it. With the current container's actual network (`eneo`)
supplied explicitly, the complete golden integration assertion passed. A
rebuild is still required to prove that Compose injects the checkout-scoped
network name automatically.

The frontend image contains Bun at `/home/vscode/.bun/bin/bun`, but its path is
not exported by the interactive shell and the frozen workspace dependencies
were initially incomplete. After `bun install --frozen-lockfile`, the focused
suite passed under the Node-compatible runtime bundled with Pyright. Node 26's
experimental global web storage must be disabled so jsdom owns `localStorage`:
`NODE_OPTIONS=--no-experimental-webstorage`. No authored or lock files changed
during dependency repair.

The focused Playwright command selected `tests/flows.spec.ts` and
`tests/ai-builder-journey.spec.ts` against the repository-managed isolated E2E
stack. A standalone production build completed in 4m1.414s, proving that the
original 180-second `webServer` timeout was too short. The timeout now allows
six minutes and nested Compose resolves the host workspace mount when invoked
inside the devcontainer. A stale reusable E2E image then failed on its missing
`libsndfile`; that image was rebuilt from the current Dockerfile. The user
explicitly deferred further E2E-stack work, so authentication and both journey
assertions remain uncollected rather than failed product assertions.

Mutmut 3.7.0 is now the selected backend mutation runner. The pre-cut command
targeted the Builder action policy, architecture commit, commit invariance,
send lease, and budget-settings modules with 94 focused tests. It generated 473
mutants: 311 killed, 144 survived, and 18 uncovered. The tested-mutant score is
68.4%. Phase 1's 70% floor applies to files actually edited during separation;
these Builder modules will be restored unchanged on the stacked branch and are
therefore exempt until Phase 2, where the 80% critical-file floors become
binding.

## Process and schema baseline

The Flows branch adds two private long-running Compose services:

- `celery-worker-flows`
- `celery-beat-flows`

Both mount the application and Docker socket and sit beside the shared Redis
and database services. Phase 4's target is zero Flow-private worker/scheduler
services and one platform task technology; these two names are the explicit
before-cut process count.

Historical Builder migrations remain on the core branch through Phase 4. Phase
1 removes only the three Builder ORM table classes and runtime registrations
from core source. The historical revisions themselves are restored on the
stacked Builder branch and replaced only by the final stacked revision in
Phase 5.

## Builder backend ownership inventory

Dedicated Builder-owned roots that move to the stacked branch:

- `backend/src/eneo/flows/ai_builder/`
- `backend/src/eneo/flows/flow_ai_builder_budget_settings.py`
- `backend/scripts/ai_builder_*`
- `backend/scripts/fixtures/ai_builder_battle/`
- `backend/tests/**/flows/ai_builder/`
- `backend/tests/integration/flows/test_ai_builder_*`

The external integration inventory is broader than direct Python imports. The
core cut must neutralize every item below while leaving manual create, publish,
run, review, artifact, evidence, retention, tenancy, and audit behavior intact.

| Boundary | Core files/touchpoints to neutralize | Stacked-branch responsibility |
|---|---|---|
| API registration | Flow router includes the Builder router | Restore routes without duplicating core routers |
| Error/OpenAPI contract | Server-level Builder exception handler, operation retagging, and SSE schema hoist | Restore Builder-only error and streaming schemas |
| Dependency injection | Main container imports and constructs Builder repository/service | Restore factories from the stacked integration commit |
| Tables | Three Builder ORM classes and Builder enum imports in the consolidated Flow table module | Own all three classes on the Builder branch until Phase 5 revision split |
| Retention | Data-retention service imports `SessionStatus` and purges Builder sessions | Restore Builder session purge on the stacked branch |
| Settings and limits | Budget models, policy resolution/update methods, routes, hard limits, and `Limit` projection fields | Restore budget surface and audit assertion on the stacked branch |
| Authorization | `BUILDER_*` Flow actions, `flows_ai_builder` permission, predefined-role grant, scoped-space helpers | Restore explicit permission and tenant/space tests |
| Audit | Builder action/entity types, category mappings, and frontend label coverage | Restore all required Builder action types and label assertions |
| Configuration | Conversation budgets, provider timeouts, and send-lease settings | Restore settings with validation on the stacked branch |
| Core authoring handoff | Builder authoring origin, Builder metadata envelope, and AI Builder resource-binding source | Retain only on the stacked branch; commit still calls the normal core draft-validation boundary |
| Retention/file references | Builder session-file checks in history purge and schema-doc exporter | Restore only where Builder tables exist |
| JSONB ownership | Builder session/planning/error envelope entries | Restore with Builder models on stacked branch |

The direct import scan currently finds Builder imports in the data-retention
service, consolidated Flow table module, Flow router, main container, and
settings service. The semantic touchpoints above also cover the known plan
breakpoints in settings router, server main, access policy, and audit-label
coverage even when they do not import the Builder package directly.

## Builder frontend ownership inventory

Dedicated Builder-owned roots that move to the stacked branch:

- `frontend/apps/web/src/lib/features/flows/ai-builder/`
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/ai-builder/`
- `frontend/apps/web/tests/ai-builder-*.spec.ts`

Mixed frontend touchpoints to neutralize in core and restore once on the
stacked branch:

- permission helpers and permission-label maps;
- audit-action labels;
- admin Flow settings load/save UI and tests for Builder budgets;
- Flow list/create dialog Builder entry points, draft rows, and session links;
- Flow editor/card affordances that return to Builder;
- `aiBuilderDrafts`, list-row projection, and their tests;
- Eneo JS settings endpoint methods and types;
- generated fetch/resource/schema types after backend route removal;
- the 424 authored translation keys in each locale.

The stacked branch must keep the Swedish conversation, clarification, progress,
error-recovery, approval, and editable-draft handoff. The core branch must keep
the manual Swedish create-to-editor route and must expose no Builder navigation
or orphaned accessible names.

## Separation gates before the first deletion

- [x] Frozen reference commit and develop merge-base recorded.
- [x] Core and Builder source/test LOC recorded separately.
- [x] Core and Builder unit duration and backend coverage recorded separately.
- [x] Table, migration, translation, and private-process counts recorded.
- [x] Backend and frontend external touchpoints inventoried.
- [x] Repair devcontainer Docker-socket access and pass the manual golden integration journey.
- [ ] Pass both manual and Builder Playwright journeys (explicitly deferred by the user; focused Builder unit tests are green).
- [x] Select and run the mutation-test command against the pre-cut reference files.
- [x] Capture a fresh-database upgrade result on the historical chain.

Until the four unchecked prerequisites are green, Phase 1 Wave 2 should not
delete Builder implementation from the core branch. Inventory and environment
repairs are safe to continue because they do not alter the measured product
behavior.
