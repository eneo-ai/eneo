# Batch 11.3a Retrospective - Proposal Resource Reference Material

## TL;DR

1. Slice 11.3a makes proposal-time resource material come from `AIBuilderResourceCatalog`.
2. Available resource refs and selected MCP refs now share one typed material shape.
3. Free-form resource descriptions are bounded before prompt rendering.
4. The slice does not add selectable assistant refs or form-field lifecycle changes.
5. Validation passed, including the full AI Builder unit suite.

## Result

| Area | Outcome |
|---|---|
| Resource material owner | `AIBuilderResourceCatalog` now builds frozen resource-reference material from the same catalog used for validation. |
| Proposal prompt | `ai_builder_plan_proposal_task.py` consumes catalog material and no longer has prompt-local resource dict helpers. |
| MCP selection | Selected MCP server/tool lines come from the same material object as the available-resource block. |
| Description budget | `RESOURCE_DESCRIPTION_MAX_CHARS = 240` clamps descriptions in catalog material. |
| Assistant refs | Intentionally absent until a tenant/workspace-scoped allow-list, permission rule, and materializer behavior exist. |

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| Proposal material lists exact catalog refs for models, knowledge, MCP servers, and MCP tools. | pass | `backend/tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py` |
| Selected MCP material uses the same catalog material. | pass | `backend/src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py` |
| Unknown selected MCP refs are not rendered as allowed refs. | pass | `test_plan_proposal_prompt_drops_selected_mcp_ref_that_is_not_in_catalog`. |
| Descriptions are bounded by a catalog-owned constant. | pass | `RESOURCE_DESCRIPTION_MAX_CHARS = 240`; clamp and boundary tests. |
| Prompt-local resource helpers are deleted. | pass | Exact grep for `_resource_ref(`, `_resource_display_name`, `_resource_description`, and `normalize_ai_builder_mcp_resources` in the proposal task returned no matches. |
| No assistant-ref placeholder was added. | pass | Proposal prompt test asserts `assistant_ref` is absent. |
| No compatibility/deprecation path was added. | pass | Anti-slippage gate passed. |

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

## Follow-Ups

| Item | Owner |
|---|---|
| Form-field declare-only, chain, multi-reference goldens and Pattern Registry decision. | 11.3b |
| Discovery-time resource material consolidation. | 11.3 follow-up after proposal rendering stabilizes |
| Selectable assistant refs with allow-list, permission, and materializer rules. | Future resource-contract slice |

## Risk

| Risk | Mitigation |
|---|---|
| Discovery prompt rendering still has a localized resource path. | Documented and deferred; proposal path now establishes the typed material shape first. |
| Future assistant refs could be mistaken as missed work. | Deferral trigger is explicit in the plan, journal, and this retrospective. |
| Prompt text changes could alter model behavior. | Focused prompt tests and the full AI Builder unit suite passed; manual smoke remains a Batch 11 follow-up gate. |

Confidence: high.
