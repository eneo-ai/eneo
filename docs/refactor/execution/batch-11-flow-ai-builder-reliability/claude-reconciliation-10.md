# Batch 11.3a Claude Reconciliation - Proposal Resource Reference Material

## TL;DR

1. Claude rejected the first 11.3a plan because it mixed resource material with under-proved form-field lifecycle work.
2. The accepted plan narrowed 11.3a to proposal-time resource material and moved form-field lifecycle work to 11.3b.
3. Implementation routes available resources and selected MCP refs through one catalog-owned typed material shape.
4. Claude green-lit the implementation and final verification with minimum score `9`.
5. One accepted tightening added a stale selected-MCP ref regression test.

## Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-3a-form-field-resource-plan-20260503T061515Z.md` | `changes_required` | `no` | 6 | Split 11.3a resource work from 11.3b form-field lifecycle work. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-3a-resource-plan-verification-20260503T061940Z.md` | `green` | `yes` | 8 | Accepted the narrowed resource-material plan. |

## Accepted Plan Findings

| Finding | Resolution |
|---|---|
| Pattern Registry sufficiency for multi-reference form-field lifecycle was under-proved. | Moved form-field goldens and the Pattern Registry decision to 11.3b. |
| Available-resource and selected-MCP rendering could still drift. | 11.3a routes both through `AIBuilderResourceReferenceMaterial`. |
| Form-field golden scope overlapped existing tests. | 11.3b now has a scenario matrix that names existing overlap and required new assertions. |
| Discovery rendering was unscoped. | Explicitly deferred; proposal rendering is the draft-emitting path and establishes the typed material shape first. |
| Description prompt budget needed an owner. | `RESOURCE_DESCRIPTION_MAX_CHARS = 240` lives in the catalog. |
| Assistant-ref deferral needed a trigger condition. | Future assistant refs require tenant/workspace allow-listing plus permission and materializer rules. |

## Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-3a-resource-implementation-20260503T062808Z.md` | `green` | `yes` | 9 | Accepted implementation; requested one non-blocking stale selected-MCP ref test. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-3a-resource-final-verification-20260503T063337Z.md` | `green` | `yes` | 9 | Accepted final source, tests, and docs; warned to stage only 11.3a files. |

## Accepted Implementation Finding

| Finding | Resolution |
|---|---|
| Selected MCP refs not present in the catalog are now dropped; pin that as the intended catalog-truth behavior. | Added `test_plan_proposal_prompt_drops_selected_mcp_ref_that_is_not_in_catalog`. |

## Final Shape

| Concept | Owner |
|---|---|
| Exact proposal resource material | `AIBuilderResourceReferenceMaterial` built by `ai_builder_resource_catalog.py`. |
| Proposal resource policy text | `ai_builder_plan_proposal_task.py`. |
| Description clamp | `RESOURCE_DESCRIPTION_MAX_CHARS = 240`. |
| Selected MCP server/tool material | `AIBuilderResourceReferenceMaterial.selected_mcp_servers` and `.selected_mcp_tools`. |
| Assistant refs | Intentionally absent until a future selectable-assistant resource contract exists. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py -q` | Passed: `15 passed`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1738 passed, 4 skipped`, 12 existing warnings. |
| `cd backend && uv run pyright ...` for 11.3a touched source/tests | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check ...` for 11.3a touched source/tests | Passed. |
| `cd backend && uv run ruff format --check ...` for 11.3a touched source/tests | Passed. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed. |
| `git diff --check -- <11.3a touched paths>` | Passed. |
| Claude final verification | Passed: `green`, minimum score `9`. |

## Carry-Forward

| Item | Owner |
|---|---|
| Form-field declare-only, chain, multi-reference goldens and Pattern Registry expression decision. | 11.3b |
| Discovery-time resource material consolidation through the catalog material shape. | 11.3 follow-up |
| Passing a single prebuilt catalog from planner orchestration into proposal and canonicalization paths. | Future resource-material cleanup |

Confidence: high.
