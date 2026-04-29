# Phase 1 Reviewer Plan

TL;DR:
1. Phase 1 is documentation-only and writes only under `docs/refactor/phase1/`.
2. The ten `prompt.md` reviewers remain the core parallel discovery team.
3. Two Phase 1b cross-cutting reviewers are added after the ten prompt reviewers to protect Single Source of Truth.
4. Reviewers must cite file:line evidence, name current owners, propose canonical homes, and include delete/merge paths.
5. Phase 2 cannot start until all Phase 1a and Phase 1b outputs are complete and reviewed for contradictions.

## Phase 1a Prompt Reviewers

| Output | Reviewer Scope | Primary Lens |
|---|---|---|
| `01-ai-builder.md` | `backend/src/intric/flows/ai_builder/**`, AI-builder frontend, AI Builder tests | AI Builder module ownership, planner/materializer/protocol boundaries |
| `02-flow-runtime.md` | Flow runtime, execution, Celery tasks, cancellation, retries | Runtime reliability and persisted lifecycle |
| `03-frontend.md` | Flow SvelteKit routes and `frontend/apps/web/src/lib/features/flows/**` | Frontend state ownership and generated/manual type boundaries |
| `04-dead-and-legacy.md` | Shims, compatibility paths, dead exports/tests, fallback/repair paths | Deletion and canonical import paths |
| `05-api-consumer.md` | Public flow API as external developer journey | API consumer DX, error model, OpenAPI/client usability |
| `06-data-model.md` | SQLAlchemy flow tables, JSONB fields, repositories, migrations | Data model constraints, indexes, typed JSON contracts |
| `07-comments-readability.md` | Names, comments, long functions, AI slop, week-one comprehension | Human readability |
| `08-tests.md` | Flow unit/integration/frontend tests | Behavior coverage, over-mocking, dead tests, high-ROI gaps |
| `09-api-maintainer.md` | Router/schema/test maintainability and endpoint evolution | API maintainer DX |
| `10-maintainability-interfaces.md` | Cross-package interfaces, fake seams, pass-through services, deep modules | Interface value and architecture boundaries |

## Phase 1b Cross-Cutting Reviewers

Phase 1b reviewers begin only after `01` through `10` are written. They must read those Phase 1a outputs as input, resolve contradictions, and avoid redoing package-level inventories unless needed to name a canonical owner.

| Output | Reviewer Scope | Primary Lens |
|---|---|---|
| `11-concept-invariants.md` | Status state machine, published definition JSON contract, principal/auth, evidence/provenance, runtime input/file upload | Single Source of Truth and canonical concept owners |
| `12-observability-operability.md` | Logs, metrics, audit events, Celery queue/beat, crash recovery, validation commands, runbooks | Production operability and incident readiness |

## Shared Contract

Each reviewer must:

- read `prompt.md`, `AGENTS.md`, `docs/engineering/*.md`, and `docs/refactor/phase0/*.md`;
- avoid source, test, migration, dependency, git, and generated-client changes;
- start with a five-line TL;DR;
- include "No findings." where a requested section is empty;
- use file:line evidence for concrete claims;
- name current owner, proposed canonical home, and merge/delete path;
- separate environmental/tooling failures from product architecture findings;
- include acceptance criteria, tests required, risk/trade-off, human reviewability impact, and confidence;
- end with the score dimensions required for that reviewer, plus any cross-review dimension gaps.

Phase 1b concept sections should stay near two pages per concept. Overflow belongs in a deferred PRD work item, not in another monolithic review doc.

## Baseline Signals To Reuse

| Signal | Value |
|---|---|
| Backend type gate | `cd backend && uv run pyright` passes |
| Backend test collection | `cd backend && ./.venv/bin/python -m pytest --collect-only` passes |
| Flow-scoped Ruff | Fails with 18 import-order issues under flow source/tests |
| Frontend check | Fails repo-wide; flow-scoped diagnostics are listed in `docs/refactor/phase0/baseline.md` |
| Frontend unit tests | `pnpm -C frontend/apps/web test:unit -- --run` runs Vitest but fails because `jsdom` is missing; 57/63 test files and 460/460 collected tests passed before unhandled environment errors |
| Docker exec | Blocked by current no-approval policy; do not treat as app failure |
