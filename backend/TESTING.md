# Backend testing guide

How the backend test suite is organized, how to run it fast, and the rules that
keep it from growing without bound. The frontend counterpart lives at
[`frontend/TESTING.md`](../frontend/TESTING.md).

## The layers

| Layer | Where | What it exercises | Infra |
|---|---|---|---|
| Unit | `tests/unit/<mirror of src/eneo>/` | One module in isolation, collaborators mocked | None |
| Integration | `tests/integration/<domain>/` | Real DB, real DI container, HTTP via ASGI client | Testcontainers (pgvector + redis), auto-marked `integration` by path |
| Migration | `tests/integration/migrations/` | Alembic downgrade/upgrade cycles | Own Postgres container per file, marker `migration_isolation`, excluded from default runs |
| E2E | `frontend/apps/web/tests/` (Playwright) | Full stack through the browser | Compose stack, see the frontend guide |

**Push tests down.** Every behavior should be tested at the lowest layer that
can express it. If a unit test can prove the behavior, do not write an
integration test for it; integration tests exist for wiring (routing, auth,
DB constraints, transactions), not for re-proving business logic.

## Where a test lives

The placement rule is deterministic so both humans and AI agents can apply it:

> A unit test for `src/eneo/X/Y.py` lives at `tests/unit/X/test_Y*.py`.
> An integration test lives at `tests/integration/<domain>/`.
> Never create files under `tests/unittests/` (frozen legacy, see below).

Before creating a new test file, search for an existing test file for the same
module and extend it. New sibling files (`test_foo_extra.py`,
`test_foo_more_cases.py`) are almost always the wrong move.

`tests/unittests/` is the legacy unit root. It is frozen: editing existing
files is fine, adding files fails the `check_test_layout.py` guard. Its
contents migrate into `tests/unit/` domain by domain (see "Legacy migration
status").

## Running the tests

All commands run inside the devcontainer. The `task` presets are the intended
day-to-day interface:

```bash
task test          # unit suite, parallel (-n auto), explicit paths, no integration collection
task test:lf       # re-run last failures, serial, stops at first failure (the debug loop)
task test:feature -- skills   # one integration domain dir, serial
task test:int      # full integration suite, -n 4, loadgroup distribution
task test:migrations          # the migration_isolation suite (slow, one container per file)
```

Raw pytest equivalents, when you need more control:

```bash
cd backend
uv run pytest tests/unit/spaces -q                  # one dir
uv run pytest tests/integration/skills -q           # one integration domain
uv run pytest tests/path/test_file.py::test_name    # one test
uv run pytest -m migration_isolation tests/integration/migrations -q
```

Notes:

- Prefer explicit paths over `-m "not integration"`: pytest then never visits
  the integration tree at all, which removes most of the collection cost.
- Parallelism lives in the presets, not in `pytest.ini`. Do not add `-n` to
  `addopts`; per-worker container boot makes small targeted runs slower and
  `-n` breaks `-x` and `--pdb`.
- Coverage is CI's job. Local runs stay coverage-free (coverage adds 20-40%
  runtime).

## Markers

`--strict-markers` is on: an undeclared marker is a collection error. The
canonical list lives in `pytest.ini`:

- `integration`: applied automatically by
  `tests/integration/conftest.py::pytest_collection_modifyitems` to everything
  under `tests/integration/`. Never write `@pytest.mark.integration` by hand;
  the guard rejects it.
- `migration_isolation`: schema downgrade/upgrade tests. Deselected by default
  (`addopts`), run explicitly via `task test:migrations`. In CI they run when
  `backend/alembic/**` changes and on a weekly cron.

Do not write `@pytest.mark.asyncio` either: `asyncio_mode = auto` makes it a
no-op, and the guard rejects it.

## Fixtures

- Root `tests/conftest.py`: warning filters, session event loop, shutdown
  watchdog. Nothing DB-related.
- `tests/integration/conftest.py`: the heavy machinery. Session-scoped
  containers (pgvector pg16 + redis, one set per xdist worker), one Alembic
  `upgrade head` per session, then per-test cleanup: full TRUNCATE plus reseed
  of tenant/user/default models. Integration fixture plugins live under
  `tests/integration/fixtures/` and are only registered for the integration
  tree; unit tests cannot (and must not) use them.
- `tests/integration/object_content/conftest.py`: adds a second Postgres
  (pg13) and a SeaweedFS S3 container. Its tests are pinned to a single xdist
  worker via `xdist_group("object_content")` so only one such stack ever
  boots.
- In devcontainer mode the compose-provided `db`/`redis` are reused instead of
  testcontainers; each xdist worker gets its own Redis DB index.
- Digest-pinned images (`pgvector/pgvector:pg13@sha256:...`,
  `chrislusf/seaweedfs@sha256:...` in the object_content conftest) must be
  pulled **on the host** before the first run: image pulls from inside the
  devcontainer fail on the dev-containers credential helper, and a tag-pulled
  image does not satisfy a digest reference. Symptom: every object_content
  test errors with `ImageNotFound`/`404 ... containers/create`.

Warnings are errors (`filterwarnings = error`). If you must ignore one, add a
structured entry to `tests/warning_filters.py`; each entry declares a reason
and a resolution path and is printed in the terminal summary.

## Writing tests

- Extend existing files; only create a file when the module has none.
- Test behavior, not implementation. Asserting that a mock was called with the
  exact arguments the code passes is a tautology; assert on outcomes.
- No redundant decorators (`asyncio`, `integration`), enforced by the guard.
- Test comments describe the invariant being protected, not the history of the
  code ("regression in X" style comments do not age well).
- Integration tests get a domain directory (`tests/integration/<domain>/`),
  not a pile of flat files.

## Deleting tests

Pruning is part of normal work. A test is deletable when ANY of these holds:

1. Its coverage is a strict subset of a same-or-lower-layer test asserting the
   same behavior.
2. It asserts implementation details (mock-echo) and a behavior-level test for
   the same path exists.
3. It duplicates a test in another root for the same route/service. Keep the
   lowest-layer version, unless the integration version exercises real
   cross-component wiring the unit version cannot.
4. It cannot fail (asserts on its own fixtures, or has no meaningful
   assertion).

Cite the criterion per deleted file in the PR description. The quarterly
redundancy report (`scripts/test_redundancy_report.py`, driven by
`pytest --cov-context=test`) produces ranked candidates for criteria 1 and 4.

## Guards

`scripts/check_test_layout.py` runs in commit preflight, pre-push, and CI. It
enforces:

1. No new files under `backend/tests/unittests/` (snapshot allow-list).
2. New files under `backend/tests/unit/` must sit in a directory mirroring an
   existing `src/eneo/` package (the current flat files are allow-listed until
   their domain migrates).
3. No `@pytest.mark.asyncio` or explicit `@pytest.mark.integration` under
   `backend/tests/`.
4. Every directory containing `test_*.py` has an `__init__.py`.
5. Allow-list entries must still exist on disk, so the lists only shrink.

When it fails, the message tells you exactly where the file belongs. If you
believe the guard is wrong, fix the guard in the same PR and say why.

## Legacy migration status

The `tests/unittests/` allow-list inside `scripts/check_test_layout.py` is the
tracker: it only shrinks, and when it is empty the directory is gone.

Consolidation happens opportunistically, one domain per PR, when a domain is
being touched anyway. Priority order (worst duplication first): api_keys,
audit, SCIM, skills, then the rest. A domain PR does:

1. `git mv backend/tests/unittests/<domain> backend/tests/unit/<domain>`
   (rename detection preserves blame).
2. Fold in any flat `tests/unit/test_<domain>_*.py` files.
3. Delete duplicates citing the four criteria above.
4. Shrink the allow-list.
5. Optional: mutation spot-check on `src/eneo/<domain>` before/after (mutmut),
   never suite-wide.
