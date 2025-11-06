/** @typedef {import('../types/resources').Integration} Integration */
/** @typedef {import('../types/resources').TenantIntegration} TenantIntegration */
/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initIntegrations(client) {
  return {
    /**
     * List all integrations available to this intric instance.
     * @throws {IntricError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/integrations/", { method: "get" });
      return res.items;
    },

    tenant: {
      /**
       * List integrations enabled for the current tenant.
       * @throws {IntricError}
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
        const res = await client.fetch("/api/v1/integrations/tenant/{integration_id}/", {
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
        const res = await client.fetch("/api/v1/integrations/tenant/{tenant_integration_id}/", {
          method: "delete",
          params: {
            path: { tenant_integration_id }
          }
        });

        return res;
      }
    },

    knowledge: {
      /**
       * Preview to knowledge items that can be imported through this integration
       * @param {{id: string}} integration UserIntegration
       * @throws {IntricError}
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
       * @param {import('../types/resources').IntegrationKnowledgePreview} args.preview The preview item received from calling the preview
       * @param {{id: string}} args.space Space to add this to
       * @param {{id: string}} args.embedding_model Embedding model to use
       *
       * @throws {IntricError}
       * */
      import: async ({ integration, preview, space, embedding_model }) => {
        const { id: user_integration_id } = integration;
        const { id } = space;
        const { key, name, url, folder_id, folder_path, type } = preview;
        await client.fetch("/api/v1/spaces/{id}/knowledge/integrations/{user_integration_id}/", {
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
              embedding_model
            }
          }
        });
      },

      /**
       * Preview to knowledge items that can be imported through this integration
       * @param {Object} args
       * @param {{id: string}} args.knowledge UserIntegration
       * @param {{id: string}} args.space Space to add this to
       *
       * @throws {IntricError}
       * */
      delete: async ({ knowledge, space }) => {
        const { id: integration_knowledge_id } = knowledge;
        const { id } = space;
        await client.fetch("/api/v1/spaces/{id}/knowledge/{integration_knowledge_id}/", {
          method: "delete",
          params: {
            path: { integration_knowledge_id, id }
          }
        });
      },

      /**
       * Get paginated sync history for an integration knowledge
       * @param {Object} args
       * @param {{id: string}} args.knowledge IntegrationKnowledge
       * @param {number} args.skip Number of items to skip (default: 0)
       * @param {number} args.limit Maximum number of sync logs per page (default: 10)
       * @throws {IntricError}
       * */
      getSyncLogs: async ({ knowledge, skip = 0, limit = 10 }) => {
        const { id: integration_knowledge_id } = knowledge;
        const res = await client.fetch("/api/v1/integrations/sync-logs/{integration_knowledge_id}/", {
          method: "get",
          params: {
            path: { integration_knowledge_id },
            query: { skip, limit }
          }
        });
        return res;
      }
    },

    user: {
      /**
       * List integrations available for the current user.
       * @throws {IntricError}
       * */
      list: async () => {
        const res = await client.fetch("/api/v1/integrations/me/", { method: "get" });
        return res.items.sort((a, b) => a.name.localeCompare(b.name));
      },

      /**
       * Disconnect a specfic integration for a user
       * @param {{id: string}} integration UserIntegration
       *
       * @returns {Promise<true>} true on success, otherwise will throw
       * @throws {IntricError}
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
       * OAuth flow: Get an url where the user can authenticate for this specific integration
       *
       * @param {{integration: {tenant_integration_id: string}, state?: string}} args
       * @throws {IntricError}
       * */
      getAuthUrl: async ({ integration, state }) => {
        const res = await client.fetch("/api/v1/integrations/auth/{tenant_integration_id}/url/", {
          method: "get",
          params: {
            path: integration,
            query: { state }
          }
        });

        return res.auth_url;
      },

      /**
       * OAuth flow: Pass the callback code / auth token to the backend
       *
       * @param {{integration: {tenant_integration_id: string}, code: string}} args
       * @throws {IntricError}
       * */
      registerAuthCode: async ({ integration, code }) => {
        const { tenant_integration_id } = integration;
        const res = await client.fetch("/api/v1/integrations/auth/callback/token/", {
          method: "post",
          requestBody: {
            "application/json": { auth_code: code, tenant_integration_id }
          }
        });

        return res;
      }
    }
  };
}
