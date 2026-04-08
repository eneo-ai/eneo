# Pyright Hardening Handoff

This branch is a typing-hardening pass for the Python backend. The branch has now reached `0 errors, 0 warnings` under a global Pyright `strict` configuration.

## Current Direction

- Keep Pyright as the single source of truth for Python typing.
- Prefer real type fixes over suppressions, `Any`, or config loopholes.
- Treat any new Pyright diagnostic as a regression.
- Optimize for explicit contracts that are easy for both humans and AI agents to follow.

## Latest Verified State

Latest full verified run on this branch:

```bash
cd backend
uv run pyright
```

Result at the latest full checkpoint:

- `0 errors`
- `0 warnings`
- `681` files analyzed

Important note:

- `uv run pyright` is now the real full-repo gate in both CI and pre-commit.
- The project now uses global `typeCheckingMode: "strict"` rather than `standard` plus a strict allowlist.
- A changed-file typecheck script can still be useful locally, but it is not the merge gate.
- Full `ruff check` for the whole backend repository is still noisy because of existing import-order debt in `alembic/` and `tests/`.

## What This Branch Established

- `backend/pyrightconfig.json` now uses a minimal global `strict` configuration.
- `backend/docs/TYPE_CHECKING.md` now documents a zero-warning global-strict policy.
- The temporary ratcheting phase is complete. `strict` path lists and per-rule warning/error overrides are no longer needed.
- Local stubs under `backend/typings/` were added for third-party packages without bundled typing support, so global strict can stay enabled without weakening config.

## Remaining Follow-Ups

Typing cleanup is no longer the bottleneck. The remaining work is architecture and runtime verification:

- Resolve the duplicate `CompletionModel` split between `ai_models.completion_models` and `completion_models.domain`.
- Complete the `EmbeddingModelLegacy` → `EmbeddingModel` migration at repository/datastore boundaries.
- Consider changing `BaseRepository.all()` to return `Sequence[Entity]` to remove invariance pressure and future override debt.
- Audit `enable_transcription_models_service.get_model_id_by_name` so the return type matches reality at all callers.
- Keep the `sessions.to_sessions_paginated_response(cursor: Optional[datetime])` contract aligned across callers and callees.
- Run the broader pytest and runtime/container smoke verification that was outside the Pyright loop.

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
