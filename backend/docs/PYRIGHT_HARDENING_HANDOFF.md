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
- `1955 warnings`
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
- `src/intric/database/tables/base_class.py` upgraded to `Mapped[]` syntax (`IdMixin`/`TimestampMixin`) — eliminated `Column[UUID]`/`Column[datetime]` warnings across all 44 ORM table modules
- `src/intric/spaces/space_repo.py` 130 → 2 warnings
- `src/intric/users/user_service.py` and `user_router.py` 120 → 0 warnings
- `src/intric/analysis/analysis_service.py` and `analysis_router.py` 95 → 0 warnings
- `src/intric/crawler/crawler.py` and `src/intric/websites/presentation/website_router.py` 83 → 0 warnings
- `src/intric/assistants/` module 59 → 1 warning

## Biggest Remaining Warning Clusters

Latest full checkpoint top rule families:

- `reportCallInDefaultInitializer`: `353`
- `reportUnknownMemberType`: `292`
- `reportArgumentType`: `243`
- `reportUnknownVariableType`: `213`
- `reportUnknownArgumentType`: `185`
- `reportMissingSuperCall`: `144`
- `reportUnknownParameterType`: `118`
- `reportUnnecessaryCast`: `114`
- `reportImplicitOverride`: `99`
- `reportMissingTypeArgument`: `59`

Latest full checkpoint top module clusters:

- `integration`: `302`
- `files`: `122`
- `templates`: `101`
- `tenants`: `96`
- `websites`: `81`
- `services`: `70`
- `spaces`: `67`
- `ai_models`: `66`
- `embedding_models`: `65`
- `settings`: `62`
- `group_chat`: `58`
- `info_blobs`: `57`
- `mcp_servers`: `56`
- `apps`: `55`
- `feature_flag`: `50`

## Recommended Next Order

1. Finish `integration` (largest remaining cluster at 302)
2. Finish `files` (122) and `templates` (101)
3. Finish `tenants` (96), `websites` (81), `services` (70)
4. Mop up remaining `spaces` (67) and `assistants` warnings (3 left, 2 require cross-file changes)
5. Re-run full Pyright and continue ratcheting warnings down
6. Once warning debt is materially lower, convert more warnings into errors and expand `strict` coverage further

## Cross-File Follow-Ups Identified by Cleanup Pass

Routed during the parallel cleanup but not yet applied (each requires touching a shared file outside the cleaned slice):

- `space_factory.py`: `security_classification` parameter should accept `Optional[SecurityClassificationDBModel]` (DB type)
- `group_chat/domain/entities/group_chat.py`: annotate `metadata_json` with concrete `dict[str, object]`
- `assistants/assistant_table.py`: change `Mapped[Optional[dict]]` → `Mapped[Optional[dict[str, object]]]` for `completion_model_kwargs` and `metadata_json`
- `authentication/auth_service.py`: `create_assistant_api_key(assistant_id: int)` should be `assistant_id: UUID`
- `assistants/assistant.py:141`: `completion_model` property needs explicit `CompletionModel | None` return type
- `tenants/tenant_repo.py`: `TenantRepository.get()` should return `TenantInDB | None`
- `main/container/container.py`: declare `user_creation_service: providers.Factory[...]` and other untyped factory providers
- `website_crud_service.py`: narrow `find_on_organization_space` return to `dict[str, Any] | None`
- `crawler/crawler_settings_helper.py`: `get_crawler_setting` generic `T` is unconstrained — overloads per setting name would resolve `Unknown` at all call sites globally

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
