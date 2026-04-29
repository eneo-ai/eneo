# Implementation Order

TL;DR:
1. Execute the refactor in dependency batches, not by the Phase 2 ROI ranking.
2. Batch 0 pins behavior, classifies Tier A/Tier B deletion candidates, and deletes only source-only false owners.
3. Runtime features are intentionally late because they require lifecycle, permission, API, frontend, audit, and test foundations.
4. Testing and documentation happen throughout, with cleanup after behavior coverage exists.
5. Stop after each batch and review before continuing.
6. Batch 0 source/test checkpoint exists on this branch at `d6a9365e477b83651d94566f58a9a7e13d0b9363`; governance/docs cleanup must land, or be explicitly waived by the user, before Batch 1 starts.

## Batch Table

| Batch | PRDs Included | Prerequisites | Expected Result | Validation Commands |
|---:|---|---|---|---|
| 0 | PRD-001, parts of PRD-007 and PRD-008 | Readiness and execution docs | Behavior pins; Tier A/Tier B kill-list classification; true source-only shim deletion after pins; route/OpenAPI tests replacing identity tests. | `docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright`; `docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest tests/unit/test_flow_openapi_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py -q`; plus exact commands for any additional Batch 0 pin tests created in the plan. |
| 1 | PRD-004 API source truth | Batch 0 | OpenAPI upload/evidence/pagination/client basics aligned; generated schema ready to be trusted. | Backend OpenAPI tests; targeted `frontend/packages/intric-js` tests after env fix |
| 2 | PRD-002 permissions/data contracts | Batch 0; coordinate with Batch 1 for API shape | Typed flow access policy, JSONB/versioning policy, permission migration map, idempotency retention. | Permission matrix tests; parser round-trip tests; pyright |
| 3 | PRD-003 lifecycle foundation, PRD-009 terminal audit | Batches 1 and 2 | Canonical lifecycle projection, status predicate sweep, idempotent terminalization command, and durable audit/outbox policy. | Runtime worker contract, stale reconciliation, task timeout, duplicate terminalization, audit outbox tests |
| 4 | PRD-003 per-step file mapping | Batches 1-3 | `step_inputs` is canonical; top-level `file_ids` source contract removed; attempt-scoped input/output file mappings added; client/docs/tests updated. | API file mapping contract; runtime resolver test; migration/count proof; client wrapper test |
| 5 | PRD-006 generated frontend types | Batch 1 | Manual Flow API/runtime types replaced by generated aliases; frontend type drift reduced. | `pnpm -C frontend check`; package type/import smoke tests |
| 6 | PRD-005 AI Builder contract split | Batches 1, 2, 5 | Prompt-as-contract audit, proposal/planner split, thinner router, maintained repair behavior. | AI Builder integration tests; SSE event tests; frontend AI Builder tests |
| 7 | PRD-006 frontend state owners | Batch 5; coordinate with Batch 6 for AI Builder | AI Builder mirroring removed, authoring/run-launch/evidence/status owners clarified. | Frontend component tests; app check |
| 8 | PRD-003 step rerun | Batches 3, 4, 5 | DAG-aware rerun endpoint/command, `flow_run_rerun_operations`, audit, idempotency, and evidence invalidation. | Rerun API+worker test; permission matrix; frontend status test |
| 9 | PRD-003 human review pause/edit/resume | Batches 3, 4, 5, 8 optional | DB state machine plus thin Celery resume task; checkpoint/yield/resume feature with audit/evidence/frontend support. | Pause/resume runtime integration; duplicate resume; stale edit conflict; evidence export; frontend journey |
| 10 | PRD-009 full operability, PRD-007/008 cleanup, PRD-010 docs | All prior batches as needed | Runbooks, dashboards/metrics, dead test deletion, readability cleanup, ADRs updated. | Full targeted backend/frontend suites; docs diff review |

## Post-Batch-0 Governance Gate

Batch 0 source/test work is committed at
`d6a9365e477b83651d94566f58a9a7e13d0b9363` on
`feature/refactor-flows-flowai` as of 2026-04-29. If the branch is
later rebased or squashed, the Batch 0 journal remains the durable
record of the checkpoint.

Before Batch 1 starts, the post-Batch-0 governance/docs cleanup must
land or be explicitly waived by the user. That cleanup makes the
durable agent contract, docs tracking policy, batch handoff rules, and
Eneo branding/namespace policy explicit.

## Branding And Namespace Migration Touchpoints

The durable policy lives in `AGENTS.md`. This order document records
where the migration questions must be handled:

- Batch 5 must include the frontend generated-client/package naming
  decision, including whether `frontend/packages/intric-js` should
  become Eneo-named or remain stable with a documented external
  migration path.
- Batch 10 must include translation, audit, telemetry, and docs
  branding cleanup, plus the namespace migration ADR/backlog.
- Python package namespace migration from `backend/src/intric` to
  `backend/src/eneo` is out of scope for these batches until a
  dedicated post-stability sizing spike inventories pyproject
  entrypoints, Alembic, Docker/Helm/deployment refs, scripts, env
  vars, generated clients, DB prefixes, and external consumers.

## Recommended Threading

Open a new implementation thread per batch. Use the canonical input
list in `docs/refactor/execution/loop-protocol.md`; for each batch,
resolve "the PRD(s) for this batch" from the Batch Table above and
include `docs/refactor/execution/batch-{N}-{name}/journal.md` if
continuing a batch.

Use `phase3/reconciled-plan.md`, accepted ADRs, and `phase0/baseline.md` as supporting context when the batch touches decisions or known tooling caveats.

Per-batch execution artifacts live under `docs/refactor/execution/batch-{N}-{name}/`. Start each batch by copying the templates from `docs/refactor/execution/batch-template/` into that batch directory, then follow `docs/refactor/execution/loop-protocol.md`.

Do not mix Batch 8 or 9 runtime feature work into earlier foundation batches.

## Branch Strategy

Use one long-running initiative branch for the refactor:
`feature/refactor-flows-flowai`.

Recommended sequence:

1. Batch 0 source/test checkpoint already exists on
   `feature/refactor-flows-flowai`.
2. Land or explicitly waive the post-Batch-0 governance/docs cleanup
   before Batch 1 starts.
3. Run all implementation batches on this branch, one batch at a time.
4. Keep each batch reviewable through curated
   `docs/refactor/execution/batch-{N}-{name}/` artifacts, validation
   summaries, and concise commits.
5. By default agents do not commit, push, merge, or open PRs unless
   the user explicitly asks.
6. Rebase or refresh `feature/refactor-flows-flowai` from `develop`
   between batches when needed.

Do not create one branch per batch unless the human owner changes this
strategy. The branch is single; the batch directories, plans,
retrospectives, reconciliations, and commit boundaries carry the review
structure.

## Commit And PR Strategy

Prefer small, human-reviewable commits grouped by behavior or
mechanical change. A good commit message is concise:

```text
flows: pin route and startup behavior

TL;DR:
- Adds route/OpenAPI behavior coverage before deleting router callable tests.
- Adds startup/import smoke coverage for canonical Flow modules.
- Leaves persisted/public compatibility readers documented for later batches.

Why:
- Batch 0 needs behavior pins before source-only false-owner deletion.
```

Keep commit bodies short. Use bullets for what changed and why; do
not paste full retrospectives, validation logs, or Claude reviews into
commit messages.

For the final PR, prefer a squash merge into the target branch unless
the repository policy requires merge commits. Squashing keeps the
long-running refactor branch's internal checkpoint commits out of the
mainline while preserving the curated execution history, plans,
journals, retrospectives, and Claude reconciliations in
`docs/refactor/execution/`. Raw logs and transcripts may remain local
and ignored when the curated artifacts summarize their outcome. The PR
body should include a TL;DR, batch list, validation summary, known
risks, and links to the batch artifacts.

## Validation Caveats

Phase 0 captured known baseline issues:

- Flow-scoped Ruff import ordering failures.
- Frontend check failures in flow files.
- Frontend Vitest missing `jsdom` environment after many tests pass.
- `docker exec` was blocked by the current no-approval policy in this Codex session.

Prefer Docker validation in implementation sessions. The default
backend command prefix is:

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1
```

Do not assume the Docker Compose project name is a container name.
Before the first validation run in a fresh implementation thread, run:

```bash
docker ps --format '{{.Names}}'
```

Use the matching backend service container. Prefer
`eneo-41ae93-eneo-1` for this workspace; VS Code devcontainer setups
may use a name such as `eneo_devcontainer-eneo-1`. Record the chosen
container name in the batch journal before interpreting failures. If
Docker is unavailable, use local backend commands only as an explicit
fallback and record that choice in the batch journal.

Implementation sessions should fix or explicitly isolate baseline
environment failures before claiming a product regression.
