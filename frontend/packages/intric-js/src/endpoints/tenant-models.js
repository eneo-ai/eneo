/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initTenantModels(client) {
  return {
    /**
     * List all Completion Models for the tenant.
     * @param {Object} [options]
     * @param {string} [options.providerId] Filter by provider ID
     * @param {boolean} [options.activeOnly] Only return active models
     * @throws {IntricError}
     * */
    listCompletion: async (options) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/completion/", {
        method: "get",
        params: {
          query: {
            provider_id: options?.providerId,
            active_only: options?.activeOnly
          }
        }
      });

      return res;
    },

    /**
     * Create a new Completion Model.
     * @param {Object} model
     * @param {string} model.provider_id Provider ID
     * @param {string} model.name LiteLLM model identifier
     * @param {string} model.display_name User-friendly name
     * @param {Object} [model.capabilities] Model capabilities
     * @param {Object} [model.default_params] Default parameters
     * @param {Object} [model.param_constraints] Parameter constraints
     * @param {boolean} [model.is_active] Whether model is active
     * @param {boolean} [model.is_default] Whether this is the default model
     * @param {string} [model.security_classification_id] Security classification ID
     * @throws {IntricError}
     * */
    createCompletion: async (model) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/completion/", {
        method: "post",
        requestBody: {
          "application/json": model
        }
      });

      return res;
    },

    /**
     * Update a Completion Model.
     * @param {{id: string}} model
     * @param {Object} update
     * @throws {IntricError}
     * */
    updateCompletion: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/completion/{id}/", {
        method: "put",
        params: { path: { id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete a Completion Model.
     * @param {{id: string}} model
     * @throws {IntricError}
     * */
    deleteCompletion: async ({ id }) => {
      await client.fetch("/api/v1/admin/tenant-models/completion/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
    },

    /**
     * List all Embedding Models for the tenant.
     * @param {Object} [options]
     * @param {string} [options.providerId] Filter by provider ID
     * @param {boolean} [options.activeOnly] Only return active models
     * @throws {IntricError}
     * */
    listEmbedding: async (options) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/embedding/", {
        method: "get",
        params: {
          query: {
            provider_id: options?.providerId,
            active_only: options?.activeOnly
          }
        }
      });

      return res;
    },

    /**
     * Create a new Embedding Model.
     * @param {Object} model
     * @throws {IntricError}
     * */
    createEmbedding: async (model) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/embedding/", {
        method: "post",
        requestBody: {
          "application/json": model
        }
      });

      return res;
    },

    /**
     * Update an Embedding Model.
     * @param {{id: string}} model
     * @param {Object} update
     * @throws {IntricError}
     * */
    updateEmbedding: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/embedding/{id}/", {
        method: "put",
        params: { path: { id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete an Embedding Model.
     * @param {{id: string}} model
     * @throws {IntricError}
     * */
    deleteEmbedding: async ({ id }) => {
      await client.fetch("/api/v1/admin/tenant-models/embedding/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
    },

    /**
     * List all Transcription Models for the tenant.
     * @param {Object} [options]
     * @param {string} [options.providerId] Filter by provider ID
     * @param {boolean} [options.activeOnly] Only return active models
     * @throws {IntricError}
     * */
    listTranscription: async (options) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/transcription/", {
        method: "get",
        params: {
          query: {
            provider_id: options?.providerId,
            active_only: options?.activeOnly
          }
        }
      });

      return res;
    },

    /**
     * Create a new Transcription Model.
     * @param {Object} model
     * @throws {IntricError}
     * */
    createTranscription: async (model) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/transcription/", {
        method: "post",
        requestBody: {
          "application/json": model
        }
      });

      return res;
    },

    /**
     * Update a Transcription Model.
     * @param {{id: string}} model
     * @param {Object} update
     * @throws {IntricError}
     * */
    updateTranscription: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/transcription/{id}/", {
        method: "put",
        params: { path: { id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete a Transcription Model.
     * @param {{id: string}} model
     * @throws {IntricError}
     * */
    deleteTranscription: async ({ id }) => {
      await client.fetch("/api/v1/admin/tenant-models/transcription/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
    }
  };
}
