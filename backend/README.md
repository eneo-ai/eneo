# Eneo backend

## Documentation

- [Type Checking](docs/TYPE_CHECKING.md) - Pyright baseline setup and local commands

## Type Checking

Run Pyright against the canonical backend devcontainer:

```bash
./scripts/run_pyright_in_devcontainer.sh
```

Useful variants:

```bash
./scripts/run_pyright_in_devcontainer.sh --stats
./scripts/run_pyright_in_devcontainer.sh src/eneo/files/file_router.py
```

## Per-branch databases

Switching git branches when a feature branch has applied Alembic migrations
normally forces a manual downgrade or a wipe. Instead, every branch owns its own
database in the devcontainer Postgres, named `eneo_<sanitized-branch>`.

A branch's database is created once, by cloning the database of the branch it was
created from. After that, switching branches only repoints `backend/.env`'s
`POSTGRES_DB`. Nothing is copied on a switch, so there is no save step and no way
to lose a branch's data by forgetting one: switch away and back and it is exactly
as you left it.

### Commands

```bash
./scripts/dev-db.sh switch     # create if needed, repoint .env, alembic upgrade head
./scripts/dev-db.sh status     # branch, database, size, base, alembic revision
./scripts/dev-db.sh prune      # list databases whose branch is gone (--yes to drop)
./scripts/dev-db.sh fork NAME  # scratch copy before something destructive
```

Also available as `task db`, `task db:status`, and `task db:prune`.

`switch` kicks the backend's Postgres connection, so restart the backend (and the
worker, if running) afterwards. The exact command is printed. Everything is
discovered from the running compose project, so no container names are hardcoded.

### Which branch does a new one clone from?

First match wins:

1. `--base <branch>`
2. `git config branch.<name>.eneoDbBase`
3. the branch this one was created from, per its git reflog
4. the nearest ancestor branch that already has a database
5. `develop`

The result is recorded in `git config` so it stays stable, and you can inspect or
change it:

```bash
git config branch.$(git branch --show-current).eneoDbBase
```

Rules 3 and 4 are skipped when the candidate has no database yet, since there
would be nothing to clone. If a stacked branch should start from its parent's
schema rather than `develop`, check the parent out and run `switch` there first.

### Inspecting state

```bash
./scripts/dev-db.sh status
```

For raw SQL, the container is discovered the same way the script does it:

```bash
DB=$(docker ps --filter label=com.docker.compose.service=db --format '{{.Names}}' | head -1)
docker exec -i "$DB" psql -U postgres -c "\\l" | grep eneo_
```

### What is not isolated per branch

Only Postgres is. Redis is shared, so ARQ jobs queued on one branch run against
whichever database is active when the worker picks them up. Object storage is
shared too, though the `object-content` compose service is off by default.

Branch names are sanitized by lowercasing and dropping every character outside
`[a-z0-9_]`, with `/` mapped to `_`. Hyphens are deleted rather than mapped, so
`feat/foo-bar` and `feat/foobar` would collide on one database.

## Environment variables

| Variable                         | Required | Explanation                                              |
|----------------------------------|----------|----------------------------------------------------------|
| OPENAI_API_KEY                   |          | Api key for openai                                       |
| ANTHROPIC_API_KEY                |          | Api key for anthropic                                    |
| AZURE_API_KEY                    |          | Api key for azure                                        |
| AZURE_MODEL_DEPLOYMENT           |          | Deployment for azure                                     |
| AZURE_ENDPOINT                   |          | Endpoint for azure                                       |
| AZURE_API_VERSION                |          | Api version for azure                                    |
| POSTGRES_USER                    | x        |                                                          |
| POSTGRES_PASSWORD                | x        |                                                          |
| POSTGRES_PORT                    | x        |                                                          |
| POSTGRES_HOST                    | x        |                                                          |
| POSTGRES_DB                      | x        |                                                          |
| REDIS_HOST                       | x        |                                                          |
| REDIS_PORT                       | x        |                                                          |
| MOBILITYGUARD_DISCOVERY_ENDPOINT |          |                                                          |
| MOBILITYGUARD_CLIENT_ID          |          |                                                          |
| MOBILITYGUARD_CLIENT_SECRET      |          |                                                          |
| OBJECT_CONTENT_INLINE_MAXIMUM_BYTES |          | Operator safety ceiling for one PostgreSQL-inline payload |
| MAX_IN_QUESTION                  | x        | Max files in a question                                  |
| SKILL_MAX_BINDINGS               |          | One-time seed for the Skill runtime-policy migration; the stored tenant policy owns the limit afterwards |
| USING_ACCESS_MANAGEMENT          | x        | Feature flag if using access management (example: False) |
| USING_AZURE_MODELS               | x        | Feature flag if using azure models (example: False)      |
| API_PREFIX                       | x        | Api prefix - eg `/api/v1/`                               |
| API_KEY_LENGTH                   | x        | Length of the generated api keys                         |
| API_KEY_HEADER_NAME              | x        | Header name for the api keys                             |
| JWT_AUDIENCE                     | x        | Example: *                                               |
| JWT_ISSUER                       | x        |                                                          |
| JWT_EXPIRY_TIME                  | x        | In seconds. Determines how long a user should be logged in before they are required to login again |
| JWT_ALGORITHM                    | x        | Example: HS256                                           |
| JWT_SECRET                       | x        |                                                          |
| JWT_TOKEN_PREFIX                 | x        | In the header - eg `Bearer`                              |
| URL_SIGNING_KEY                  | x        | Key for temporary file access URLs (use a strong random string) |
| LOGLEVEL                         |          | one of ´INFO´, ´DEBUG´, ´WARNING´, ´ERROR´               |


## Federation Flag

- `FEDERATION_ENABLED` is the primary flag for database-configured federation.
- `FEDERATION_PER_TENANT_ENABLED` is still accepted as a deprecated fallback alias.

## Federation Migration

The env-to-tenant federation migration no longer runs during app startup.

Run it manually when needed:

```bash
python scripts/migrate_env_oidc_to_tenant_federation.py
```

The script uses the current backend environment and exits without changes if federation is disabled, the OIDC env config is incomplete, or the tenant state is not eligible for migration.
