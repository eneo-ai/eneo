# Type Checking (Pyright)

Pyright is the source of truth for backend type checking. We do not run `mypy` in CI.

## Current Policy

- Global config uses `standard` mode from `backend/pyrightconfig.json`.
- A small legacy backlog still remains as warnings globally:
  - `reportArgumentType`
  - `reportGeneralTypeIssues`
  - `reportIncompatibleMethodOverride`
  - `reportIncompatibleVariableOverride`
  - `reportPossiblyUnboundVariable`
  - `reportUnknownVariableType`
- Selected backend modules are enforced with real Pyright `strict` mode through the `strict` path list in `backend/pyrightconfig.json`.
- New modules should be added to the `strict` list as soon as they are clean enough to carry it.
- `reportUnknownArgumentType` and `reportUnknownMemberType` are intentionally not enabled globally yet because they currently explode into downstream follow-on noise. Fix the sources first, then enable the downstream rules.

## What It Checks

- Scope: `backend/src/intric/**/*.py` only.
- CI and pre-commit both run `uv run pyright` from `backend/`.
- `tests` and `alembic` are excluded by config.
- The modules listed in `strict` are held to stricter rules than the rest of the codebase.

## What It Does Not Check

- Frontend or non-`src/intric` Python code.
- Tests and migrations.

## Local Commands

### Full backend run

```bash
cd backend
uv run pyright
```

### Useful stats

```bash
cd backend
uv run pyright --stats
```

### Single file

```bash
cd backend
uv run pyright src/intric/files/file_router.py
```

## Editor Support

Install the VS Code Pylance extension. It uses the same engine as Pyright and reads `pyrightconfig.json` automatically.

## Working Rules

- Add explicit return types on public router, service, repository, and adapter methods.
- Keep `Unknown` from leaking across boundaries. Prefer `TypedDict`, Pydantic models, or narrow casts at integration edges.
- Treat `reportUnknownVariableType` warnings as backlog to eliminate, not as acceptable steady-state noise.
- Use SQLAlchemy 2.0 typed patterns (`Mapped[...]`, `mapped_column()`) when touching ORM models.
- Use `# pyright: ignore[...]` only with a specific rule and only when the escape hatch is justified.
- When you clean up a module enough that it passes strict, add its path to the `strict` list in `backend/pyrightconfig.json`.
