# Pyright Hardening Handoff

This branch is a typing-hardening pass for the Python backend with the explicit goal of reaching global `strict` and eventually `0 errors, 0 warnings`.

## Current Direction

- Keep Pyright as the single source of truth for Python typing.
- Prefer real type fixes over suppressions, `Any`, or config loopholes.
- Treat warnings as visible backlog that should be driven to zero over time.
- Optimize for explicit contracts that are easy for both humans and AI agents to follow.

## Latest Verified State

Latest full verified run on this branch:

```bash
cd backend
uv run pyright
```

Result at the latest full checkpoint:

- `0 errors`
- `2499 warnings`
- `681` files analyzed

Important note:

- Full `ruff check` for the whole backend repository is still noisy because of existing import-order debt in `alembic/` and `tests/`.
- Targeted `ruff check` runs for the touched backend slices passed during this hardening pass.

## What This Branch Established

- `backend/pyrightconfig.json` now exposes a much broader warning baseline.
- `backend/docs/TYPE_CHECKING.md` documents the stricter typing direction.
- Several backend areas were pushed to clean or near-clean local states to prove the approach works without resorting to weak typing.

## Areas Already Cleaned Aggressively

These slices were either verified at `0 errors / 0 warnings` or brought materially closer while unblocking full-repo Pyright:

- `src/intric/database`
- `src/intric/sessions`
- `src/intric/model_providers`
- `src/intric/completion_models`
- `src/intric/authentication`
- `src/intric/server`
- `src/intric/worker`
- `src/intric/audit`
- `src/intric/templates` errors were eliminated
- `src/intric/integration` repo-blocking errors were eliminated

## Biggest Remaining Warning Clusters

Latest full checkpoint top rule families:

- `reportCallInDefaultInitializer`: `449`
- `reportUnknownMemberType`: `411`
- `reportArgumentType`: `347`
- `reportUnknownArgumentType`: `292`
- `reportUnknownVariableType`: `287`
- `reportMissingSuperCall`: `154`
- `reportUnknownParameterType`: `154`

Latest full checkpoint top module clusters:

- `integration`: `290`
- `spaces`: `209`
- `users`: `147`
- `files`: `123`
- `websites`: `115`
- `analysis`: `110`
- `templates`: `107`
- `tenants`: `96`
- `assistants`: `88`
- `crawler`: `74`

Latest full checkpoint top files:

- `src/intric/spaces/space_repo.py`
- `src/intric/users/user_service.py`
- `src/intric/users/user_router.py`
- `src/intric/analysis/analysis_service.py`
- `src/intric/analysis/analysis_router.py`
- `src/intric/websites/presentation/website_router.py`
- `src/intric/crawler/crawler.py`
- `src/intric/ai_models/ai_models_service.py`
- `src/intric/files/text.py`
- `src/intric/mcp_servers/presentation/mcp_server_router.py`

## Recommended Next Order

1. Finish `spaces` and `assistants`
2. Finish `integration`
3. Finish `sysadmin`, `api`, and router-heavy surfaces
4. Finish `websites`, `crawler`, and `users`
5. Re-run full Pyright and continue ratcheting warnings down
6. Once warning debt is materially lower, convert more warnings into errors and expand `strict` coverage further

## Fix Strategy

Use these principles when continuing:

- Replace loose dicts with `TypedDict` or typed models where the shape is stable.
- Tighten repository and service return types before fixing leaf call sites.
- Prefer typed helper functions over repeated inline narrowing.
- Fix ORM typing at the boundary instead of casting at every usage site.
- Avoid `Any` unless the external API is truly dynamic and the boundary is explicitly isolated.
- Avoid `# pyright: ignore` except for narrow, documented cases.

## Verification Commands

Use these commands as the default loop:

```bash
cd backend
uv run pyright
uv run ruff check src/intric
```

When working a bounded slice, run Pyright on that slice first and then re-run the full backend check before merging.
