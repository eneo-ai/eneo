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

## Per-branch database snapshots

Switching git branches when a feature branch has applied Alembic migrations normally forces a manual downgrade or a wipe. Two helper scripts at the repo root turn this into a `git stash`-like workflow against the devcontainer Postgres.

The active database (`backend/.env`'s `POSTGRES_DB`, typically `postgres`) is never renamed. Instead, branch state lives in side databases named `eneo_<sanitized-branch>`, plus a baseline `eneo_develop`.

### Scripts

- `./scripts/dev-db-init.sh` — bring the active DB to the right state for the current branch. Restores `eneo_<branch>` if a snapshot exists, otherwise clones from `eneo_develop`. Runs `alembic upgrade head` at the end. On first run it offers to bootstrap `eneo_develop` from the current active DB.
- `./scripts/dev-db-commit.sh` — save the current active DB as `eneo_<branch>`. Overwrites any prior snapshot for that branch. Run before switching away if you want to come back to this exact state.

Both scripts kick the backend's Postgres connection during the clone/drop; restart the backend (and worker, if running) afterwards. The exact restart command is printed by `dev-db-init.sh`.

### Typical loop

```bash
git checkout new-feature
./scripts/dev-db-init.sh         # clones from eneo_develop (first time on this branch)
# ...work, add a migration, mutate data...
./scripts/dev-db-commit.sh       # snapshot before switching away

git checkout other-feature
./scripts/dev-db-init.sh         # restores eneo_other_feature (or clones develop if none yet)
```

### One-off: bootstrap `eneo_develop` when you're already on a feature branch

If the branch has migrations beyond `develop` and you want to seed the baseline without losing work:

```bash
# 1. Save current branch state
./scripts/dev-db-commit.sh

# 2. Find develop's alembic head by reading the down_revision of the branch's
#    first new migration:
git diff develop...HEAD --name-only -- alembic/versions/ | head -1
# then: grep down_revision <that-file>

# 3. Still on the branch (so alembic sees branch migrations), downgrade active to develop's head
docker exec -u vscode eneo_devcontainer-eneo-1 bash -i -c \
  "cd /workspace/backend && uv run alembic downgrade <develop-head-rev>"

# 4. Switch git, then bootstrap
git checkout develop
./scripts/dev-db-init.sh         # answer 'y' to the bootstrap prompt
```

The branch snapshot from step 1 is untouched by step 3, so `git checkout <branch> && ./scripts/dev-db-init.sh` restores it later.

### Inspecting state

```bash
docker exec -i eneo_devcontainer-db-1 psql -U postgres -c "\l" | grep eneo_
docker exec -i eneo_devcontainer-db-1 psql -U postgres -d eneo_<branch> \
  -c "select version_num from alembic_version;"
```

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
| UPLOAD_FILE_TO_SESSION_MAX_SIZE  | x        | Max text file size for uploading to a session            |
| UPLOAD_IMAGE_TO_SESSION_MAX_SIZE | x        | Max image file size for uploading to a session           |
| UPLOAD_MAX_FILE_SIZE             | x        | Max file size for uploading to a collection              |
| TRANSCRIPTION_MAX_FILE_SIZE      | x        | Max file size for uploading to a collection              |
| MAX_IN_QUESTION                  | x        | Max files in a question                                  |
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
