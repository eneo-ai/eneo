# Eneo Flows Refactor Review

TL;DR:
1. This is a documentation-only architecture, maintainability, API, data-model, runtime, frontend, test, and operability review of Eneo Flows and Flow AI Builder.
2. The current architecture is not production-ready for lifecycle expansion; the overall current-state score is 3/10 because status lifecycle, terminalization, JSONB contracts, generated types, tests, and frontend state ownership are split.
3. Claude and Gemini challenged the Phase 2 plan; Phase 7 adds the final implementation-readiness gate, Celery-only runtime decisions, JSONB/relational decisions, and deletion-ready inventories.
4. No source, tests, migrations, dependencies, git branches, commits, pushes, or PRs were changed.
5. The next implementation work should start from `phase4/refactor-plan.md`, `implementation-order.md`, `phase7/implementation-readiness.md`, `execution/implementation-bootstrap.md`, `execution/loop-protocol.md`, `execution/retrospective-checklist.md`, and the PRD for that batch.

## Scope

The review follows `prompt.md`, the pasted `AGENTS.md` rules, and the local engineering standards under `docs/engineering/`.

Covered areas:

- backend Flow API, application services, runtime executor, Celery tasks, SQLAlchemy tables, migrations, audit, permissions
- Flow AI Builder backend and frontend contracts
- frontend Flow authoring, runtime, evidence, AI Builder state, generated client usage
- tests, OpenAPI, generated TypeScript, observability, runbooks, comments/readability, deletion opportunities

## Ground Rules Followed

| Rule | Status |
|---|---|
| Modify only review/planning/PRD output under `docs/refactor/` | Followed |
| Do not change source, tests, migrations, dependencies, or generated clients | Followed |
| Do not commit, push, create branches, or open PRs | Followed |
| Cite concrete claims with file:line evidence | Followed throughout generated docs |
| Use Claude peer review for non-trivial direction changes | Followed; Phase 0 and Phase 3 Claude artifacts preserved under `.codex/artifacts/` |
| Give Claude the requested 25-minute Phase 3 timeout | Followed; first 240s timeout was rerun with `ASK_CLAUDE_TIMEOUT_SECONDS=1500` |

## Document Index

| Path | Summary |
|---|---|
| `phase0/baseline.md` | Repo/head info, tooling results, hotspots, environment limitations, command baseline. |
| `phase0/repository-map.md` | Backend, AI Builder, frontend, tests, API routers, data model, and Celery map. |
| `phase0/maintainability-standards.md` | Standards applied during review. |
| `phase0/claude-challenge-response.md` | Phase 0 Claude challenge, local verification, and accepted revisions. |
| `phase1/README.md` | Phase 1 reviewer scopes and output contract. |
| `phase1/01-ai-builder.md` | AI Builder backend/frontend architecture and hotspot review. |
| `phase1/02-flow-runtime.md` | Flow runtime lifecycle, terminalization, idempotency, crash recovery, feature gaps. |
| `phase1/03-frontend.md` | Frontend state ownership, generated type drift, component responsibilities. |
| `phase1/04-dead-and-legacy.md` | Dead code, compatibility, kill list, persisted-shape gates. |
| `phase1/05-api-consumer.md` | External API journey and per-step mapping, rerun, human review gaps. |
| `phase1/06-data-model.md` | SQLAlchemy/data-model/JSONB/permission/idempotency review. |
| `phase1/07-comments-readability.md` | Comment classification, names, readability hotspots. |
| `phase1/08-tests.md` | Test pyramid, missing contracts, implementation-coupled tests. |
| `phase1/09-api-maintainer.md` | Router/schema/error/auth/OpenAPI/generated-client maintainer review. |
| `phase1/10-maintainability-interfaces.md` | Deep modules, shallow layers, interfaces, seams, DDD pragmatism. |
| `phase1/11-concept-invariants.md` | Cross-cutting canonical homes and invariant map. |
| `phase1/12-observability-operability.md` | Logs, metrics, audit, health, runbooks, operability review. |
| `phase2/synthesis.md` | 10-dimension score, top changes, dependency graph, feature sketches, kill list, ADRs. |
| `phase3/claude-review.md` | Verbatim Claude adversarial review of the Phase 2 plan. |
| `phase3/gemini-review.md` | Verbatim Gemini adversarial review of the Phase 2 plan. |
| `phase3/reconciled-plan.md` | Accepted/rejected/partial decisions and corrected execution order. |
| `phase4/refactor-plan.md` | Ordered implementation checklist grouped into seven iterations. |
| `prd/PRD-001-foundations.md` | Behavior pins, true deletion cleanup, policies, guardrails. |
| `prd/PRD-002-data-model-and-permissions.md` | Lifecycle, JSONB, principal, idempotency, permissions. |
| `prd/PRD-003-runtime-reliability-and-feature-gaps.md` | Terminalization, per-step file mapping, step rerun, human review. |
| `prd/PRD-004-api-consumer-and-api-maintainer-dx.md` | OpenAPI source truth, pagination, evidence export, error model, client DX. |
| `prd/PRD-005-ai-builder-architecture.md` | AI Builder prompt/plan/proposal/planner contracts and split. |
| `prd/PRD-006-frontend-single-source-of-truth.md` | Generated types and frontend workflow state owners. |
| `prd/PRD-007-testing-strategy.md` | API/runtime/frontend contract tests and brittle test deletion. |
| `prd/PRD-008-dead-code-comments-and-readability.md` | Shim deletion, comments, readability, migration-gated cleanup. |
| `prd/PRD-009-observability-and-operability.md` | Metrics, audit outbox, health probes, runbooks. |
| `prd/PRD-010-documentation-and-adrs.md` | ADRs, implementation order, open questions, rule proposals. |
| `phase5/codex-rules.md` | Proposed enforceable Codex/CI/code-review rules. |
| `phase5/agents-md-additions.md` | Proposal-only additions for future `AGENTS.md`. |
| `phase7/README.md` | Phase 7 implementation-readiness document index. |
| `phase7/implementation-readiness.md` | Stop/go gate and summary of final executable plan hardening. |
| `execution/implementation-bootstrap.md` | Self-contained handoff brief and Batch 0 starter prompts. |
| `phase7/data-model-scalability-stress-test.md` | JSONB vs relational decisions and scalability stress cases. |
| `phase7/dead-tests-cleanup.md` | Flow / AI Builder dead and unnecessary test cleanup inventory. |
| `phase7/comment-cleanup.md` | Executable comment classification and cleanup inventory. |
| `phase7/edge-cases-and-leakage.md` | Boundary leakage and edge-case audit. |
| `phase7/do-not-split.md` | Responsibility-based split candidates and do-not-split list. |
| `phase7/claude-reconciliation.md` | Reconciliation of Claude attacks against repository evidence. |
| `phase7/claude/` | Verbatim Claude decision-packet reviews. |
| `execution/loop-protocol.md` | Durable implementation loop protocol for every refactor batch. |
| `execution/retrospective-checklist.md` | Per-iteration self-retrospective checklist and gate rules. |
| `execution/batch-template/` | Canonical journal, plan, and retrospective templates for each batch directory. |
| `architecture-decision-backlog.md` | ADR backlog with alternatives and recommended defaults. |
| `implementation-order.md` | PRD execution batches, prerequisites, expected results, validation commands. |
| `open-questions.md` | Open questions, why they matter, owners, default recommendations. |

## Top 10 Decisions

| Rank | Decision | Source |
|---:|---|---|
| 1 | Replace ROI-only ordering with dependency-ordered implementation waves. | `phase3/reconciled-plan.md` |
| 2 | Fix flow-specific OpenAPI schema issues at endpoint/model source, not global postprocessing. | `phase3/reconciled-plan.md`, `PRD-004` |
| 3 | Make status lifecycle and terminalization canonical before rerun/review features. | `phase2/synthesis.md`, `PRD-003` |
| 4 | Delete top-level run `file_ids` as a pre-production API break, coordinated with OpenAPI/client/docs/tests. | `phase3/reconciled-plan.md`, `PRD-003` |
| 5 | Do not create runtime input/artifact tables without ADR proof of row-level need. | `phase3/reconciled-plan.md`, `PRD-002` |
| 6 | Human review must checkpoint, yield the worker, and resume via fresh dispatch. | `phase3/reconciled-plan.md`, `PRD-003` |
| 7 | Step rerun invalidation must traverse the DAG and return `invalidated_step_ids`. | `phase3/reconciled-plan.md`, `PRD-003` |
| 8 | Flow/AI Builder authorization must use `FlowPrincipal` plus typed actions; no raw request scope reads. | `phase1/09-api-maintainer.md`, `PRD-002` |
| 9 | Generated frontend types become canonical only after OpenAPI is truthful. | `phase3/reconciled-plan.md`, `PRD-006` |
| 10 | Terminal audit needs an explicit outbox/fail policy. | `phase1/12-observability-operability.md`, `PRD-009` |

## Canonical Implementation Schedule

Use `implementation-order.md` as the single source of truth for execution sequence. The "Top 10 Implementation Items" below is a summary of important changes, not a scheduling list.

## Starting An Implementation Thread

Use a fresh thread for each implementation batch. Do not ask the
agent to pre-read every Phase 0-7 document; those phases are the
evidence trail and the curated inputs below are the launch packet.
Drill into Phase 0-7 only when the launch packet cites a specific doc
or a current-batch ambiguity blocks progress.

For Batch 0:

1. Land the readiness and execution docs as a docs-only commit on the
   chosen base before source/test implementation starts.
2. Create or switch to `feature/refactor-flows-flowai`, or keep that
   branch setup instruction in the starter prompt so the implementation
   agent handles it before `/plan`.
3. Open a fresh implementation thread.
4. Paste the Batch 0 implementation starter prompt from
   `docs/refactor/execution/implementation-bootstrap.md`.
5. Read the first retrospective yourself and check the evidence
   citations, not only the GREEN/YELLOW/RED label.

Use this one initiative branch for all batches. Keep the work
reviewable through batch artifacts, focused validation, and concise
commits rather than creating a branch per batch.

## Top 10 Implementation Items

1. Add route/OpenAPI/runtime behavior pins.
2. Delete true import shims and router callable re-export surfaces.
3. Fix flow-specific OpenAPI source issues and evidence export contract.
4. Add canonical status lifecycle projection.
5. Add idempotent terminalization command with audit outbox policy.
6. Replace raw/string permission helpers with typed Flow access policy.
7. Delete top-level `file_ids` and make `step_inputs` canonical.
8. Replace manual frontend Flow API types with generated aliases.
9. Split AI Builder prompt/proposal/planner contracts by lifecycle owner.
10. Add runtime/API/frontend contract tests and operability runbooks.

## Kill List Summary

| Kill Item | Timing | Risk |
|---|---|---|
| Backend import shims: `flow_repo.py`, `flow_version_repo.py`, `flow_service.py`, `flow_run_repo.py`, `flow_dispatch.py` | Early after zero imports | Low-medium |
| `flow_run_service.py` logger-rebinding subclass shim | Early after tests retarget canonical module | Low-medium |
| Router callable re-export surfaces | Early after route tests replace identity tests | Low-medium |
| Frontend `getRedispatchFeedback` alias | Batch 10 by default; Batch 0 only if a frontend behavior pin lands first | Low-medium |
| `normalize_legacy_config` | After DB proof/backfill for HTTP configs | Medium |
| Top-level run `file_ids` | PRD-003 API migration | High |
| DOCX `template_file_id` fallback | After DB backfill to `template_asset_id` | High |
| Legacy form type normalization | After DB backfill | Medium |
| Mirrored input-template frontend cleanup | After data migration/proof | Medium |
| AI Builder `ai_builder_models.py` star barrel | AI Builder contract wave, not early cleanup | Medium-high |

## PRD Order

1. `PRD-001-foundations.md`
2. `PRD-004-api-consumer-and-api-maintainer-dx.md` for OpenAPI truth, in parallel with parts of `PRD-002` where safe
3. `PRD-002-data-model-and-permissions.md`
4. `PRD-003-runtime-reliability-and-feature-gaps.md` foundation portions
5. `PRD-009-observability-and-operability.md`
6. `PRD-006-frontend-single-source-of-truth.md`
7. `PRD-005-ai-builder-architecture.md`
8. `PRD-007-testing-strategy.md` throughout, then cleanup pass
9. `PRD-008-dead-code-comments-and-readability.md` throughout, with cleanup pass
10. `PRD-010-documentation-and-adrs.md` throughout

## Validation Notes

Phase 0 baseline:

- Backend test collection passed.
- `uv run pyright` passed.
- Flow-scoped Ruff had import-order failures.
- Frontend check had existing Flow diagnostics.
- Frontend Vitest collected/passed many tests but failed on missing `jsdom`.
- Requested `docker exec` commands were blocked by current execution policy; this is an environment limitation, not a product finding.

Run `git diff --check -- docs/refactor` before reviewing the docs.
