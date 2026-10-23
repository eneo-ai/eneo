import { createSyncDetailsLoader } from "../integrations/sync-details.js";

/** @typedef {import('../types/resources').Integration} Integration */
/** @typedef {import('../types/resources').TenantIntegration} TenantIntegration */
/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/schema').components['schemas']['IntegrationSyncProgressList']} IntegrationSyncProgressList */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initIntegrations(client) {
  const syncDetails = createSyncDetailsLoader((id, data) =>
    client.fetch("/api/v1/spaces/{id}/knowledge/integrations/sync-details/", {
      method: "post",
      params: { path: { id } },
      requestBody: { "application/json": data }
    })
  );
  return {
    /**
     * List all integrations available to this eneo instance.
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/integrations/", { method: "get" });
      return res.items;
    },

    tenant: {
      /**
       * List integrations enabled for the current tenant.
       * @throws {EneoError}
       * */
      list: async () => {
        const res = await client.fetch("/api/v1/integrations/tenant/", {
          method: "get",
          params: {
            query: {
              filter: "all"
            }
          }
        });
        return res.items.sort((a, b) => a.name.localeCompare(b.name));
      },

      /**
       * Enable an available integration for the current tenant.
       *
       * @param {{integration_id: string}} integration The integration you want to add to this tenant
       */
      enable: async (integration) => {
        const { integration_id } = integration;
        const res = await client.fetch("/api/v1/integrations/tenant/add/{integration_id}/", {
          method: "post",
          params: {
            path: { integration_id }
          }
        });

        return res;
      },

      /**
       * Enable an available integration for the current tenant.
       *
       * @param {{id: string}} integration The integration you want to add to this tenant
       */
      disable: async (integration) => {
        const { id: tenant_integration_id } = integration;
        const res = await client.fetch(
          "/api/v1/integrations/tenant/remove/{tenant_integration_id}/",
          {
            method: "delete",
            params: {
              path: { tenant_integration_id }
            }
          }
        );

        return res;
      }
    },

    knowledge: {
      /**
       * Batches concurrent source history/problem reads while keeping per-item results.
       * @param {{space: {id: string}, knowledge: {id: string}, offset?: number, limit?: number}} args
       */
      getSyncDetails: ({ space, knowledge, offset = 0, limit = 10 }) =>
        syncDetails(space.id, knowledge.id, offset, limit),
      /**
       * Preview to knowledge items that can be imported through this integration
       * @param {{id: string}} integration UserIntegration
       * @throws {EneoError}
       * */
      preview: async (integration) => {
        const { id: user_integration_id } = integration;

        const res = await client.fetch("/api/v1/integrations/{user_integration_id}/preview/", {
          method: "get",
          params: {
            path: { user_integration_id }
          }
        });
        return res.items;
      },

      /**
       * Preview to knowledge items that can be imported through this integration
       * @param {Object} args
       * @param {{id: string}} args.integration UserIntegration
       * @param {import('../types/resources').IntegrationKnowledgePreview & {folder_id?: string, folder_path?: string, resource_type?: "site" | "onedrive"}} args.preview The preview item received from calling the preview
       * @param {{id: string}} args.space Space to add this to
       * @param {{id: string}} args.embedding_model Embedding model to use
       *
       * @returns {Promise<any>} The background job processing this import
       * @throws {EneoError}
       * */
      import: async ({ integration, preview, space, embedding_model }) => {
        const { id: user_integration_id } = integration;
        const { id } = space;
        const { key, name, url, folder_id, folder_path, type, resource_type } = preview;
        const job = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/add/{user_integration_id}/",
          {
            method: "post",
            params: {
              path: { user_integration_id, id }
            },
            requestBody: {
              "application/json": {
                key,
                name,
                url,
                folder_id,
                folder_path,
                selected_item_type: type,
                resource_type: resource_type || "site",
                embedding_model
              }
            }
          }
        );
        return job;
      },

      /**
       * Import multiple knowledge items in one request.
       * @param {Object} args
       * @param {{id: string}} args.integration UserIntegration
       * @param {Array<{
       *   key?: string,
       *   name: string,
       *   url: string,
       *   folder_id?: string,
       *   folder_path?: string,
       *   type?: string,
       *   resource_type?: "site" | "onedrive"
       * }>} args.items
       * @param {string=} args.wrapper_name
       * @param {{id: string}} args.space Space to add this to
       * @param {{id: string}} args.embedding_model Embedding model to use
       *
       * @throws {EneoError}
       * */
      importBatch: async ({ integration, items, wrapper_name, space, embedding_model }) => {
        const { id: user_integration_id } = integration;
        const { id } = space;

        const response = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/add/{user_integration_id}/batch/",
          {
            method: "post",
            params: {
              path: { user_integration_id, id }
            },
            requestBody: {
              "application/json": {
                embedding_model,
                wrapper_name,
                items: items.map((item) => ({
                  key: item.key,
                  name: item.name,
                  url: item.url,
                  folder_id: item.folder_id,
                  folder_path: item.folder_path,
                  selected_item_type: item.type,
                  resource_type: item.resource_type || "site"
                }))
              }
            }
          }
        );
        return response;
      },

      /**
       * Preview to knowledge items that can be imported through this integration
       * @param {Object} args
       * @param {{id: string}} args.knowledge UserIntegration
       * @param {{id: string}} args.space Space to add this to
       *
       * @throws {EneoError}
       * */
      delete: async ({ knowledge, space }) => {
        const { id: integration_knowledge_id } = knowledge;
        const { id } = space;
        await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/remove/{integration_knowledge_id}/",
          {
            method: "delete",
            params: {
              path: { integration_knowledge_id, id }
            }
          }
        );
      },

      /**
       * Rename a SharePoint wrapper (updates all items in the wrapper).
       * @param {Object} args
       * @param {{id: string}} args.space Space where the wrapper belongs
       * @param {string} args.wrapper_id Wrapper id
       * @param {string} args.name New wrapper name
       * @throws {EneoError}
       */
      renameWrapper: async ({ space, wrapper_id, name }) => {
        const { id } = space;
        const res = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/",
          {
            method: "patch",
            params: {
              path: { id, wrapper_id }
            },
            requestBody: {
              "application/json": { name }
            }
          }
        );
        return res;
      },

      /**
       * Delete all integration knowledge items in a SharePoint wrapper.
       * @param {Object} args
       * @param {{id: string}} args.space Space where the wrapper belongs
       * @param {string} args.wrapper_id Wrapper id
       * @throws {EneoError}
       */
      deleteWrapper: async ({ space, wrapper_id }) => {
        const { id } = space;
        await client.fetch("/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/", {
          method: "delete",
          params: {
            path: { id, wrapper_id }
          }
        });
      },

      /**
       * Get paginated sync history for an integration knowledge
       * @param {Object} args
       * @param {{id: string}} args.knowledge IntegrationKnowledge
       * @param {number} args.skip Number of items to skip (default: 0)
       * @param {number} args.limit Maximum number of sync logs per page (default: 10)
       * @throws {EneoError}
       * */
      getSyncLogs: async ({ knowledge, skip = 0, limit = 10 }) => {
        const { id: integration_knowledge_id } = knowledge;
        const res = await client.fetch(
          "/api/v1/integrations/sync-logs/{integration_knowledge_id}/",
          {
            method: "get",
            params: {
              path: { integration_knowledge_id },
              query: { skip, limit }
            }
          }
        );
        return res;
      },

      /**
       * Trigger a full resync for a SharePoint integration knowledge
       * @param {Object} args
       * @param {{id: string}} args.knowledge IntegrationKnowledge to sync
       * @param {{id: string}} args.space Space where the knowledge belongs
       *
       * @returns {Promise<any>} The background job processing this sync
       * @throws {EneoError}
       * */
      triggerFullSync: async ({ knowledge, space }) => {
        const { id: integration_knowledge_id } = knowledge;
        const { id } = space;
        const job = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/sync/",
          {
            method: "post",
            params: {
              path: { id, integration_knowledge_id }
            }
          }
        );
        return job;
      },

      /**
       * List the indexed documents of an integration knowledge item, one page at a time.
       * @param {Object} args
       * @param {{id: string}} args.knowledge IntegrationKnowledge
       * @param {{id: string}} args.space Space where the knowledge belongs
       * @param {string=} args.q Matches the title or the path relative to the imported folder
       * @param {"name" | "path" | "size" | "updated_at"=} args.sort
       * @param {"asc" | "desc"=} args.order
       * @param {number=} args.limit 1..100
       * @param {number=} args.offset
       *
       * @returns {Promise<import("../types/schema").components["schemas"]["IntegrationDocumentsPage"]>}
       * @throws {EneoError}
       * */
      listDocuments: async ({ knowledge, space, q, sort, order, limit, offset }) => {
        const { id: integration_knowledge_id } = knowledge;
        const { id } = space;
        const query = Object.fromEntries(
          Object.entries({ q, sort, order, limit, offset }).filter(
            ([, value]) => value !== undefined && value !== ""
          )
        );
        const res = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/",
          {
            method: "get",
            params: {
              path: { id, integration_knowledge_id },
              query
            }
          }
        );
        return res;
      },

      /**
       * The files the newest sync of an integration knowledge item left out, with reasons.
       * @param {Object} args
       * @param {{id: string}} args.knowledge IntegrationKnowledge
       * @param {{id: string}} args.space Space where the knowledge belongs
       *
       * @returns {Promise<import("../types/schema").components["schemas"]["IntegrationSkippedDocuments"]>}
       * @throws {EneoError}
       * */
      listSkippedDocuments: async ({ knowledge, space }) => {
        const { id: integration_knowledge_id } = knowledge;
        const { id } = space;
        const res = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/skipped/",
          {
            method: "get",
            params: {
              path: { id, integration_knowledge_id }
            }
          }
        );
        return res;
      },

      /**
       * Live progress of the integration knowledge syncs running in a space.
       * Items that are not syncing are absent from the list.
       * @param {Object} args
       * @param {{id: string}} args.space Space whose integration knowledge to check
       *
       * @returns {Promise<IntegrationSyncProgressList>}
       * @throws {EneoError}
       * */
      getSyncProgress: async ({ space }) => {
        const { id } = space;
        const res = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/sync-progress/",
          {
            method: "get",
            params: {
              path: { id }
            }
          }
        );
        return res;
      },

      /**
       * Rename an integration knowledge item
       * @param {Object} args
       * @param {{id: string}} args.knowledge IntegrationKnowledge to rename
       * @param {{id: string}} args.space Space where the knowledge belongs
       * @param {string} args.name New name for the knowledge
       * @throws {EneoError}
       * */
      rename: async ({ knowledge, space, name }) => {
        const { id: integration_knowledge_id } = knowledge;
        const { id } = space;
        const res = await client.fetch(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/",
          {
            method: "patch",
            params: {
              path: { id, integration_knowledge_id }
            },
            requestBody: {
              "application/json": { name }
            }
          }
        );
        return res;
      }
    },

    user: {
      /**
       * List integrations available for the current user.
       * @throws {EneoError}
       * */
      list: async () => {
        const res = await client.fetch("/api/v1/integrations/me/", { method: "get" });
        return res.items.sort((a, b) => a.name.localeCompare(b.name));
      },

      /**
       * List integrations available for a specific space, filtered by space type and auth type.
       * - Personal spaces: Only user OAuth integrations
       * - Shared/Organization spaces: Only tenant app integrations
       * @param {{id: string}} space The space to get available integrations for
       * @throws {EneoError}
       * */
      listForSpace: async (space) => {
        const { id: space_id } = space;
        const res = await client.fetch("/api/v1/integrations/spaces/{space_id}/available/", {
          method: "get",
          params: {
            path: { space_id }
          }
        });
        return res.items.sort((a, b) => a.name.localeCompare(b.name));
      },

      /**
       * Disconnect a specfic integration for a user
       * @param {{id: string}} integration UserIntegration
       *
       * @returns {Promise<true>} true on success, otherwise will throw
       * @throws {EneoError}
       * */
      disconnect: async (integration) => {
        const { id: user_integration_id } = integration;
        await client.fetch("/api/v1/integrations/users/{user_integration_id}/", {
          method: "delete",
          params: {
            path: { user_integration_id }
          }
        });
        return true;
      },

      /**
       * OAuth flow: Get an url where the user can authenticate for this specific integration.
       * The backend generates a single-use CSRF `state` bound to the user + integration;
       * the caller must echo it back via {@link registerAuthCode}.
       *
       * @param {{integration: {tenant_integration_id: string}}} args
       * @returns {Promise<{url: string, state: string}>}
       * @throws {EneoError}
       * */
      getAuthUrl: async ({ integration }) => {
        const res = await client.fetch("/api/v1/integrations/auth/{tenant_integration_id}/url/", {
          method: "get",
          params: {
            path: integration
          }
        });

        return { url: res.auth_url, state: res.state };
      },

      /**
       * OAuth flow: Pass the callback code / auth token to the backend
       *
       * @param {{integration: {tenant_integration_id: string}, code: string, state: string}} args
       * @throws {EneoError}
       * */
      registerAuthCode: async ({ integration, code, state }) => {
        const { tenant_integration_id } = integration;
        const res = await client.fetch("/api/v1/integrations/auth/callback/token/", {
          method: "post",
          requestBody: {
            "application/json": { auth_code: code, tenant_integration_id, state }
          }
        });

        return res;
      }
    },

    admin: {
      sharepoint: {
        /**
         * List all SharePoint webhook subscriptions
         * @throws {EneoError}
         * */
        listSubscriptions: async () => {
          const res = await client.fetch("/api/v1/admin/sharepoint/subscriptions", {
            method: "get"
          });
          return res;
        },

        /**
         * Renew all expired SharePoint subscriptions
         * @throws {EneoError}
         * */
        renewExpiredSubscriptions: async () => {
          const res = await client.fetch("/api/v1/admin/sharepoint/subscriptions/renew-expired", {
            method: "post"
          });
          return res;
        },

        /**
         * Recreate every SharePoint subscription of the tenant, expired or not,
         * so Graph posts to the currently configured public address.
         * @returns {Promise<import("../types/schema").components["schemas"]["SubscriptionRenewalResult"]>}
         * @throws {EneoError}
         * */
        recreateAllSubscriptions: async () => {
          const res = await client.fetch("/api/v1/admin/sharepoint/subscriptions/recreate-all", {
            method: "post"
          });
          return res;
        },

        /**
         * Recreate a specific SharePoint subscription
         * @param {{id: string}} subscription The subscription to recreate
         * @throws {EneoError}
         * */
        recreateSubscription: async (subscription) => {
          const { id } = subscription;
          const res = await client.fetch(
            "/api/v1/admin/sharepoint/subscriptions/{subscription_id}/recreate",
            {
              method: "post",
              params: {
                path: { subscription_id: id }
              }
            }
          );
          return res;
        },

        /**
         * Test the stored SharePoint app (tenant app or service account) with a
         * full token round trip; the backend records the outcome as the app's
         * credential health.
         * @returns {Promise<import("../types/schema").components["schemas"]["TenantAppTestResult"]>}
         * @throws {EneoError}
         * */
        testStoredConnection: async () => {
          const res = await client.fetch("/api/v1/admin/sharepoint/app/test", {
            method: "post"
          });
          return res;
        },

        /**
         * Test tenant-app credentials before saving them; nothing is stored.
         * @param {{client_id: string, client_secret: string, tenant_domain: string, certificate_path?: string | null}} credentials
         * @returns {Promise<import("../types/schema").components["schemas"]["TenantAppTestResult"]>}
         * @throws {EneoError}
         * */
        testTenantAppCredentials: async (credentials) => {
          const options = /** @type {any} */ ({
            method: "post",
            requestBody: { "application/json": credentials }
          });
          const res = await client.fetch("/api/v1/admin/sharepoint/app/test", options);
          return res;
        },

        /**
         * Restart the Microsoft sign-in for the configured service account.
         * Keeps the app and its imported knowledge; the existing callback completes it.
         * @returns {Promise<{auth_url: string, state: string}>}
         * @throws {EneoError}
         * */
        restartServiceAccountAuth: async () => {
          const res = await client.fetch("/api/v1/admin/sharepoint/service-account/auth/reauth", {
            method: "post"
          });
          return res;
        }
      }
    }
  };
}
