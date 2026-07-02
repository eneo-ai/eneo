# Type Checking (Pyright)

Pyright is the source of truth for backend type checking. We do not run `mypy` in CI.

## Current Policy

- Global config uses `strict` mode from `backend/pyrightconfig.json`.
- The backend policy is `0 errors, 0 warnings` for a full `uv run pyright` run.
- There is no longer a split between globally-checked modules and a stricter allowlist. The full backend under `src/eneo` is held to the same strict standard.
- Changed-file scripts are local convenience only; they are not the gate.

## What It Checks

- Scope: `backend/src/eneo/**/*.py` only.
- CI and pre-commit both run `uv run pyright` from `backend/`.
- The gate is the full backend in strict mode.
- `tests` and `alembic` are excluded by config.

## What It Does Not Check

- Frontend or non-`src/eneo` Python code.
- Tests and migrations.

## Local Commands

When running from the host, prefer the repo script so pyright uses the backend
devcontainer and its isolated `.venv`:

```bash
bash backend/scripts/run_pyright_in_devcontainer.sh
```

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

Host equivalent:

```bash
bash backend/scripts/run_pyright_in_devcontainer.sh --stats
```

### Single file

```bash
cd backend
uv run pyright src/eneo/files/file_router.py
```

## Editor Support

Install the VS Code Pylance extension. It uses the same engine as Pyright and reads `pyrightconfig.json` automatically.

## Working Rules

- Add explicit return types on public router, service, repository, and adapter methods.
- Keep `Unknown` from leaking across boundaries. Prefer `TypedDict`, Pydantic models, or narrow casts at integration edges.
- Treat any new Pyright diagnostic as release-blocking until fixed or narrowly justified.
- Use SQLAlchemy 2.0 typed patterns (`Mapped[...]`, `mapped_column()`) when touching ORM models.
- Use `# pyright: ignore[...]` only with a specific rule and only when the escape hatch is justified.
