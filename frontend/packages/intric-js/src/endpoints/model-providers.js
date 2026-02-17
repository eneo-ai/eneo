/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initModelProviders(client) {
  return {
    /**
     * List all Model Providers for the tenant.
     * @param {Object} [options]
     * @param {boolean} [options.activeOnly] Only return active providers
     * @throws {IntricError}
     * */
    list: async (options) => {
      const res = await client.fetch("/api/v1/admin/model-providers/", {
        method: "get",
        params: {
          query: options?.activeOnly ? { active_only: true } : undefined
        }
      });

      return res;
    },

    /**
     * Get a single Model Provider by ID.
     * @param {{id: string}} provider
     * @throws {IntricError}
     * */
    get: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{id}/", {
        method: "get",
        params: { path: { id } }
      });

      return res;
    },

    /**
     * Create a new Model Provider.
     * @param {Object} provider
     * @param {string} provider.name User-defined name
     * @param {string} provider.provider_type Provider type (e.g., "openai", "vllm")
     * @param {Object} provider.credentials Provider credentials
     * @param {Object} [provider.config] Provider configuration
     * @param {boolean} [provider.is_active] Whether provider is active
     * @throws {IntricError}
     * */
    create: async (provider) => {
      const res = await client.fetch("/api/v1/admin/model-providers/", {
        method: "post",
        requestBody: {
          "application/json": provider
        }
      });

      return res;
    },

    /**
     * Update an existing Model Provider.
     * @param {{id: string}} provider
     * @param {Object} update
     * @param {string} [update.name]
     * @param {Object} [update.credentials]
     * @param {Object} [update.config]
     * @param {boolean} [update.is_active]
     * @throws {IntricError}
     * */
    update: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{id}/", {
        method: "put",
        params: { path: { id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete a Model Provider.
     * @param {{id: string}} provider
     * @param {Object} [options]
     * @param {boolean} [options.force] Force delete even if models exist
     * @throws {IntricError}
     * */
    delete: async ({ id }, options) => {
      await client.fetch("/api/v1/admin/model-providers/{id}/", {
        method: "delete",
        params: {
          path: { id },
          query: options?.force ? { force: true } : undefined
        }
      });
    },

    /**
     * List available models/deployments from the provider's own API.
     * @param {{id: string}} provider
     * @returns {Promise<Array<{name: string, model?: string, status?: string, owned_by?: string, display_name?: string}>>}
     * @throws {IntricError}
     * */
    listModels: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{id}/models/", {
        method: "get",
        params: { path: { id } }
      });

      return res;
    },

    /**
     * Get supported model types and top models per provider type from LiteLLM.
     * @returns {Promise<Record<string, {modes: string[], models: Record<string, string[]>}>>}
     * @throws {IntricError}
     * */
    getCapabilities: async () => {
      const res = await client.fetch("/api/v1/admin/model-providers/capabilities/", {
        method: "get"
      });

      return res;
    },

    /**
     * Validate that a model works with a provider by making a minimal API call.
     * @param {{id: string}} provider
     * @param {{model_name: string, model_type?: string}} body
     * @returns {Promise<{success: boolean, message?: string, error?: string}>}
     * @throws {IntricError}
     * */
    validateModel: async ({ id }, { model_name, model_type = "completion" }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{id}/validate-model/", {
        method: "post",
        params: { path: { id } },
        requestBody: {
          "application/json": { model_name, model_type }
        }
      });

      return res;
    },

    /**
     * Test provider connection.
     * @param {{id: string}} provider
     * @throws {IntricError}
     * */
    test: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{id}/test/", {
        method: "post",
        params: { path: { id } }
      });

      return res;
    }
  };
}
