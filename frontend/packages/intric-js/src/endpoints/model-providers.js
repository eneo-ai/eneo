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
        // @ts-ignore - query params accepted by backend but schema marks params as not required
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
      const res = await client.fetch("/api/v1/admin/model-providers/{provider_id}/", {
        method: "get",
        params: { path: { provider_id: id } }
      });

      return res;
    },

    /**
     * Create a new Model Provider.
     * @param {Object} provider
     * @param {string} provider.name User-defined name
     * @param {string} provider.provider_type Provider type (e.g., "openai", "vllm")
     * @param {{[key: string]: unknown}} provider.credentials Provider credentials
     * @param {{[key: string]: unknown}} [provider.config] Provider configuration
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
     * @param {{[key: string]: unknown}} [update.credentials]
     * @param {{[key: string]: unknown}} [update.config]
     * @param {boolean} [update.is_active]
     * @throws {IntricError}
     * */
    update: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{provider_id}/", {
        method: "put",
        params: { path: { provider_id: id } },
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
      /** @type {any} */
      const params = {
        path: { provider_id: id },
        query: options?.force ? { force: true } : undefined
      };
      await client.fetch("/api/v1/admin/model-providers/{provider_id}/", {
        method: "delete",
        params
      });
    },

    /**
     * List available models from the provider's own API.
     *
     * Pass ``mode`` to have the server filter the response — preferred over
     * filtering client-side so consumers (frontend pickers, external API
     * clients) get only what they need.
     *
     * @param {{id: string, mode?: "completion" | "embedding" | "transcription"}} args
     * @returns {Promise<any>}
     * @throws {IntricError}
     * */
    listModels: async ({ id, mode }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{provider_id}/models/", {
        method: "get",
        params: {
          path: { provider_id: id },
          // @ts-expect-error — `mode` is a new optional query param; this
          // typing relaxation can be removed once schema.d.ts is regenerated
          // from the backend's openapi.json (run `node update.js`).
          query: mode ? { mode } : undefined
        }
      });

      return res;
    },

    /**
     * Get the tenant's favorite provider types.
     * @returns {Promise<any>}
     * @throws {IntricError}
     * */
    getFavorites: async () => {
      const res = await client.fetch("/api/v1/admin/model-providers/favorites/", {
        method: "get"
      });

      return res;
    },

    /**
     * Set the tenant's favorite provider types.
     * @param {string[]} providers Ordered list of provider type strings
     * @returns {Promise<any>}
     * @throws {IntricError}
     * */
    setFavorites: async (providers) => {
      const res = await client.fetch("/api/v1/admin/model-providers/favorites/", {
        method: "put",
        requestBody: {
          "application/json": { providers }
        }
      });

      return res;
    },

    /**
     * Get supported model types and top models per provider type from LiteLLM.
     * @returns {Promise<any>}
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
     * @returns {Promise<any>}
     * @throws {IntricError}
     * */
    validateModel: async ({ id }, { model_name, model_type = "completion" }) => {
      const res = await client.fetch(
        "/api/v1/admin/model-providers/{provider_id}/validate-model/",
        {
          method: "post",
          params: { path: { provider_id: id } },
          requestBody: {
            "application/json": { model_name, model_type }
          }
        }
      );

      return res;
    },

    /**
     * Look up recommended default values for a model from LiteLLM.
     * @param {string} modelName The model identifier to look up
     * @returns {Promise<any>}
     * @throws {IntricError}
     * */
    getModelDefaults: async (modelName) => {
      const res = await client.fetch("/api/v1/admin/model-providers/model-defaults/", {
        method: "get",
        params: { query: { model_name: modelName } }
      });

      return res;
    },

    /**
     * Test provider connection.
     * @param {{id: string}} provider
     * @throws {IntricError}
     * */
    test: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{provider_id}/test/", {
        method: "post",
        params: { path: { provider_id: id } }
      });

      return res;
    }
  };
}
