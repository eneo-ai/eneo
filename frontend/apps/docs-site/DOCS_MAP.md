# Documentation map

Which pages on [docs.eneo.ai](https://docs.eneo.ai) describe which parts of the code. Use it in both directions:

- **Changing code?** Find the rows whose paths you touched and update those pages in the same pull request when user-visible behaviour, configuration, endpoints, defaults, commands or UI labels change. Follow [AUTHORING.md](AUTHORING.md) to choose the target branch. This map is a review aid, not an automated guarantee that the prose is current.
- **Changing docs?** Verify claims against the files listed for that page.

Page paths are relative to `frontend/apps/docs-site/src/content/`. Swedish translations use the same relative page paths under `src/content/sv/`; update existing translations together with the English page. Code paths are relative to the repository root. Globs are indicative, not exhaustive — when in doubt, the page whose subject matches wins.

## Release announcements

| Code                                                                 | Pages                                                                                                     |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `frontend/packages/whats-new/**` (on branches containing What's new) | `about/release-notes.mdx` renders the shared release data; edit `releases.json`, not a duplicate MDX list |

## Deployment and configuration

| Code                                                                                                                              | Pages                                                                      |
| --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `docs/deployment/env_*.template`, `docs/deployment/docker-compose*.yml`, `docs/deployment/*.md`, `docker/**`                      | `guides/deployment.mdx`, `index.mdx` (quick start), `guides/upgrade-*.mdx` |
| `backend/src/eneo/main/config.py` (settings, defaults, env names)                                                                 | `guides/deployment.mdx`, plus the feature page for the setting (below)     |
| `backend/src/eneo/server/main.py` (API prefix, health endpoints, middleware), `backend/src/eneo/server/routers.py` (mount points) | `docs/api.mdx`, `docs/architecture.mdx`, `guides/deployment.mdx`           |
| `.devcontainer/**`, `backend/pyproject.toml`, `backend/run.sh`, `frontend/package.json`, `Taskfile.yml`                           | `docs/getting-started.mdx`, `docs/INSTALLATION.md` (root)                  |
| `backend/alembic/versions/**` (breaking migrations, data migrations)                                                              | `guides/upgrade-*.mdx`, `docs/architecture.mdx` (data model)               |
| `docs/deployment/docker-compose.modules.yml`, `docs/deployment/env_module*.template`, `docs/deployment/MODULES.md`                | `docs/module-authentication.mdx`, `guides/deployment.mdx`                  |

## Authentication and identity

| Code                                                                                                                                                  | Pages                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `backend/src/eneo/authentication/federation_router.py`, `authentication/auth_service.py`, `settings/credential_resolver.py` (OIDC, tenant federation) | `docs/authentication-architecture.mdx`, `guides/oidc-federation/*.mdx`             |
| `backend/src/eneo/tenants/presentation/tenant_federation_router.py`                                                                                   | `guides/oidc-federation/multi-tenant.mdx`, `docs/authentication-architecture.mdx`  |
| `frontend/apps/web/src/routes/(public)/login/**` (tenant selection, login UI)                                                                         | `docs/authentication-architecture.mdx`, `guides/oidc-federation/multi-tenant.mdx`  |
| `backend/src/eneo/users/user_router.py` (login token, /users/me)                                                                                      | `docs/api.mdx`                                                                     |
| `backend/src/eneo/authentication/api_key_*.py`, `authentication/auth_models.py`, `authentication/auth_dependencies.py`, `authentication/auth.py`      | `docs/api-key-management.mdx`, `docs/api.mdx`                                      |
| `frontend/apps/web/src/routes/(app)/account/**`, `routes/(app)/admin/api-keys/**`                                                                     | `docs/api-key-management.mdx`                                                      |
| `backend/src/eneo/scim/**`, sysadmin scim-token endpoints in `backend/src/eneo/sysadmin/sysadmin_router.py`                                           | `guides/scim-provisioning.mdx`                                                     |
| `backend/src/eneo/modules/**`, `frontend/apps/web/src/routes/(public)/module-login/**`                                                                | `docs/module-authentication.mdx`                                                   |
| `backend/src/eneo/settings/encryption_service.py`, `backend/src/eneo/cli/generate_encryption_key.py`                                                  | `guides/ai-providers.mdx`, `guides/oidc-federation/*.mdx`, `guides/deployment.mdx` |

## Spaces and administration

| Code                                                                                                                                                                                                                                                                                                              | Pages                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `backend/src/eneo/spaces/oversight/**`, `frontend/apps/web/src/routes/(app)/admin/spaces/**`, `frontend/apps/web/src/lib/features/spaces/oversight/**`                                                                                                                                                            | `guides/space-oversight.mdx`, `docs/architecture.mdx`                              |
| Oversight join marker: `backend/src/eneo/spaces/space_repo.py`, `backend/src/eneo/spaces/space_factory.py`, `backend/src/eneo/spaces/api/space_assembler.py`, `frontend/apps/web/src/lib/features/spaces/components/OversightJoinNotice.svelte`, `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/members/**` | `guides/space-oversight.mdx`                                                       |
| `backend/src/eneo/audit/domain/mandatory_actions.py` (always-logged actions)                                                                                                                                                                                                                                      | `docs/audit-logging.mdx`, `guides/audit-logging.mdx`, `guides/space-oversight.mdx` |
| `backend/src/eneo/user_groups/**` (group membership changes are always logged)                                                                                                                                                                                                                                    | `guides/space-oversight.mdx`, `docs/audit-logging.mdx`, `guides/audit-logging.mdx` |

## AI models and providers

| Code                                                                                                                                                                                                     | Pages                     |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| `backend/src/eneo/model_providers/**`, `completion_models/**`, `embedding_models/**`, `transcription_models/**`, `tenants/provider_field_config.py`, `tenants/presentation/tenant_credentials_router.py` | `guides/ai-providers.mdx` |
| `frontend/apps/web/src/routes/(app)/admin/models/**`                                                                                                                                                     | `guides/ai-providers.mdx` |
| `backend/src/eneo/tokens/**`, `token_usage/**`, usage extraction in `completion_models/infrastructure/adapters/tenant_model_adapter.py`                                                                  | `docs/token-counting.mdx` |
| `backend/src/eneo/tenants/**` (`show_model_pricing`, tenant settings)                                                                                                                                    | `guides/ai-providers.mdx` |

## Knowledge, retrieval, MCP and skills

| Code                                                                                                                                                                                                                                                                                         | Pages                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `backend/src/eneo/files/**`, `info_blobs/**`, `embedding_models/infrastructure/datastore.py`, `groups_legacy/**` (upload, extraction, chunking)                                                                                                                                              | `guides/document-processing.mdx`                                               |
| `backend/src/eneo/websites/**`, `crawler/**`                                                                                                                                                                                                                                                 | `guides/document-processing.mdx`                                               |
| `backend/src/eneo/assistants/references.py`, `internal_mcp/**`, `completion_models/infrastructure/context_builder.py`                                                                                                                                                                        | `docs/knowledge-retrieval-and-mcp.mdx`                                         |
| `backend/src/eneo/mcp_servers/**`, `frontend/apps/web/src/routes/(app)/admin/mcp-servers/**`, space MCP selection UI                                                                                                                                                                         | `guides/mcp-servers.mdx`, `docs/knowledge-retrieval-and-mcp.mdx`               |
| `backend/src/eneo/skills/**`, skill permissions in `roles/**`, `frontend/apps/web/src/routes/(app)/admin/skills/**`                                                                                                                                                                          | `guides/skills.mdx`                                                            |
| `backend/src/eneo/integration/**` (SharePoint) , `frontend/apps/web/src/routes/(app)/admin/integrations/**`                                                                                                                                                                                  | `guides/sharepoint-integration.mdx`                                            |
| `backend/src/eneo/widgets/**`, `backend/src/eneo/server/dependencies/widget_auth.py`, `frontend/packages/widget-loader/**`, `frontend/apps/web/src/lib/features/widget/**`, `frontend/apps/web/src/routes/(public)/embed/**`, `frontend/apps/web/src/routes/(app)/admin/widgets/**`          | `guides/embed-widget.mdx`                                                      |
| `frontend/apps/web/src/routes/(public)/widget/**` (loader, saved settings), `frontend/apps/web/src/routes/(app)/documents/**` (source references), `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/assistants/[assistantId]/widget/**`, `WIDGET_*` in `backend/src/eneo/main/config.py` | `guides/embed-widget.mdx`                                                      |
| Visitor reach: `VISITOR_CAPABILITY_PURPOSES` in `backend/src/eneo/widgets/domain/visitor.py`, `backend/src/eneo/mcp_servers/infrastructure/identity_headers.py`, the `/{id}/widget-status/` route in `backend/src/eneo/assistants/api/assistant_router.py`                                   | `guides/embed-widget.mdx`, `guides/capabilities.mdx`, `guides/mcp-servers.mdx` |

## Storage, workers and operations

| Code                                                                                                                                                    | Pages                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `backend/src/eneo/object_content/**`, `worker/object_content_tasks.py`, `worker/upload_tasks.py`, `frontend/apps/web/src/routes/(app)/admin/storage/**` | `docs/object-content-architecture.mdx`, `guides/object-content-storage.mdx`, `docs/deployment/OBJECT_CONTENT.md` (root) |
| `backend/src/eneo/worker/**`, `jobs/**`                                                                                                                 | `docs/architecture.mdx`, `guides/object-content-storage.mdx` (drain procedure)                                          |
| `backend/src/eneo/audit/**`, `api/audit/**`, `frontend/apps/web/src/routes/(app)/admin/audit-logs/**`                                                   | `docs/audit-logging.mdx`, `guides/audit-logging.mdx`                                                                    |
| `backend/src/eneo/conversations/**`, `spaces/**`, `assistants/**` (public API shapes)                                                                   | `docs/api.mdx`                                                                                                          |
| `.github/workflows/release_sbom.yml`, `.github/workflows/build_and_push_images.yml`, `docker/seaweedfs/**`                                              | `docs/release-sboms.mdx`, `docs/object-content-architecture.mdx`                                                        |

## Project and contributing

| Code                                                                                                                                                                   | Pages                               |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `.github/workflows/ci.yml`, `.github/workflows/dependency-review.yml`, `.github/dependabot.yml`, `docs/SECURITY.md`                                                    | `contributing/security.mdx`         |
| `.github/workflows/export-roadmap.yml`, `.github/workflows/add-to-project.yml`, `.github/scripts/**`, `scripts/export_github_roadmap.mjs`, `.github/ISSUE_TEMPLATE/**` | `contributing/project-roadmap.mdx`  |
| `docs/CONTRIBUTING.md`, `docs/DEPLOYMENT_WORKFLOW.md`, `docs/CODE_QUALITY.md`                                                                                          | `contributing/index.mdx`            |
| `frontend/apps/docs-site/**`, `frontend/apps/web/src/lib/core/docs.ts` (site languages, publication and app docs links)                                                | `frontend/apps/docs-site/README.md` |
