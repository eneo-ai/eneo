# Batch 2 - Claude Reconciliation (Iteration 1)

Claude implementation review artifact:

- `.codex/artifacts/claude-peer-loop-batch-2-permissions-data-implementation-20260429T211151Z.md`

Raw local copy:

- `docs/refactor/execution/batch-2-permissions-data-contracts/claude-attack-1.md` (ignored local artifact)

## Verdict

- Claude verdict: `green`
- Claude green light: `yes`
- Claude minimum score: `8`
- Codex classification: `GREEN with accepted polish`

Claude found no blockers. Three minor findings were concrete enough to fix immediately rather than carrying them forward.

## Findings And Actions

| Finding | Claude classification | Codex classification | Action |
|---|---|---|---|
| Malformed published-definition `flow_id` used `flow_definition_steps_invalid`. | Minor | accepted | Added `FLOW_DEFINITION_FLOW_ID_INVALID`, raised it with `context={"field": "flow_id"}`, added parser test coverage, and documented the new code. |
| `flow_runs.user_id` source guard was broader than the plan's read-filter pin. | Minor / speculative until write path changes | partial | Tightened the guard to ban `FlowRuns.user_id` / `flow_runs.user_id` only in `.where(...)` / `.filter(...)` read-filter patterns outside `principal.py`. |
| `flow_router_common.audit_actor_kwargs` was a one-line pass-through. | Minor | accepted | Removed the pass-through and retargeted callers to `flow_api_common.audit_actor_kwargs`. |
| Existing `principal_type` Pydantic serialization warnings. | Observation | rejected: out-of-scope | Recorded as pre-existing follow-up; not introduced by Batch 2. |

## Verification After Fixes

- `docs/refactor/execution/batch-2-permissions-data-contracts/validation-2.log` captures the second local validation pass.
- `pytest` improved to `214 passed, 18 warnings` after the added malformed-`flow_id` parser row.
- `pyright`, `ruff`, import-linter, `git diff --check`, and source guards remained green.
- Docker validation remains blocked by host tool policy before execution.

## Carry-Forward

- Existing `principal_type` enum/string warning in evidence tests remains a later cleanup item.
- `_resolve_litellm_params` remains deferred to Batch 6 AI Builder split cleanup.
