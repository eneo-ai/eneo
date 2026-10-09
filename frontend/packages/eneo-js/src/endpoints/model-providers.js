/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initModelProviders(client) {
  return {
    /**
     * List all Model Providers for the tenant.
     * @param {Object} [options]
     * @param {boolean} [options.activeOnly] Only return active providers
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     * @param {import('../types/resources').OutboundHeaderInput[]} [provider.outbound_headers] Outbound HTTP headers
     * @throws {EneoError}
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
     * @param {import('../types/resources').OutboundHeaderInput[]} [update.outbound_headers]
     *   Replaces the configured headers. An entry with an `id` and no `value`
     *   keeps its stored value; a stored header whose `id` is absent is deleted.
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     * @param {{id: string, mode?: "completion" | "embedding" | "transcription" | "image"}} args
     * @returns {Promise<any>}
     * @throws {EneoError}
     * */
    listModels: async ({ id, mode }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{provider_id}/models/", {
        method: "get",
        params: {
          path: { provider_id: id },
          query: mode ? { mode } : undefined
        }
      });

      return res;
    },

    /**
     * Get the tenant's favorite provider types.
     * @returns {Promise<any>}
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     *
     * Pass `providerType` whenever it is known (wizard step, edit dialog of a
     * tenant-owned model, etc.). Without it the backend can only return a
     * defaulted match when exactly one provider prefixes the bare name, so
     * Azure-served gpt-4o would otherwise resolve to openai/gpt-4o prices.
     * @param {string} modelName The model identifier to look up
     * @param {string} [providerType] Canonical provider type (e.g. "openai", "azure")
     * @returns {Promise<any>}
     * @throws {EneoError}
     * */
    getModelDefaults: async (modelName, providerType) => {
      /** @type {{ model_name: string; provider_type?: string }} */
      const query = { model_name: modelName };
      if (providerType) query.provider_type = providerType;
      const res = await client.fetch("/api/v1/admin/model-providers/model-defaults/", {
        method: "get",
        params: { query }
      });

      return res;
    },

    /**
     * Test provider connection.
     * @param {{id: string}} provider
     * @throws {EneoError}
     * */
    test: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/model-providers/{provider_id}/test/", {
        method: "post",
        params: { path: { provider_id: id } }
      });

      return res;
    },

    /**
     * Metadata for the outbound header editor: the dynamic values a header
     * value may use, and the provider types that support outbound headers.
     * @returns {Promise<import('../types/resources').OutboundHeaderOptions>}
     * @throws {EneoError}
     * */
    getOutboundHeaderOptions: async () => {
      const res = await client.fetch("/api/v1/admin/model-providers/outbound-headers/options/", {
        method: "get"
      });

      return res;
    },

    /**
     * Resolve a provider's outbound headers for a user in the tenant, without
     * sending anything. A secret header returns its state only.
     * @param {{id: string}} provider
     * @param {{userId: string}} body
     * @returns {Promise<import('../types/resources').OutboundHeaderPreview>}
     * @throws {EneoError}
     * */
    previewOutboundHeaders: async ({ id }, { userId }) => {
      const res = await client.fetch(
        "/api/v1/admin/model-providers/{provider_id}/outbound-headers/preview/",
        {
          method: "post",
          params: { path: { provider_id: id } },
          requestBody: {
            "application/json": { user_id: userId }
          }
        }
      );

      return res;
    }
  };
}
