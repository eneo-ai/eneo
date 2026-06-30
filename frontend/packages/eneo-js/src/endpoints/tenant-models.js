/** @typedef {import('../client/client').EneoError} EneoError */

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
     * @throws {EneoError}
     * */
    listCompletion: async (options) => {
      /** @type {any} */
      const fetchOptions = {
        method: "get",
        params: {
          query: {
            provider_id: options?.providerId,
            active_only: options?.activeOnly
          }
        }
      };
      const res = await client.fetch("/api/v1/admin/tenant-models/completion/", fetchOptions);

      return res;
    },

    /**
     * Create a new Completion Model.
     * @param {any} model Model data (passed through to API)
     * @throws {EneoError}
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
     * @throws {EneoError}
     * */
    updateCompletion: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/completion/{model_id}/", {
        method: "put",
        params: { path: { model_id: id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete a Completion Model.
     * @param {{id: string}} model
     * @throws {EneoError}
     * */
    deleteCompletion: async ({ id }) => {
      await client.fetch("/api/v1/admin/tenant-models/completion/{model_id}/", {
        method: "delete",
        params: { path: { model_id: id } }
      });
    },

    /**
     * List all Embedding Models for the tenant.
     * @param {Object} [options]
     * @param {string} [options.providerId] Filter by provider ID
     * @param {boolean} [options.activeOnly] Only return active models
     * @throws {EneoError}
     * */
    listEmbedding: async (options) => {
      /** @type {any} */
      const fetchOptions = {
        method: "get",
        params: {
          query: {
            provider_id: options?.providerId,
            active_only: options?.activeOnly
          }
        }
      };
      const res = await client.fetch("/api/v1/admin/tenant-models/embedding/", fetchOptions);

      return res;
    },

    /**
     * Create a new Embedding Model.
     * @param {any} model
     * @throws {EneoError}
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
     * @throws {EneoError}
     * */
    updateEmbedding: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/embedding/{model_id}/", {
        method: "put",
        params: { path: { model_id: id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete an Embedding Model.
     * @param {{id: string}} model
     * @throws {EneoError}
     * */
    deleteEmbedding: async ({ id }) => {
      await client.fetch("/api/v1/admin/tenant-models/embedding/{model_id}/", {
        method: "delete",
        params: { path: { model_id: id } }
      });
    },

    /**
     * List all Transcription Models for the tenant.
     * @param {Object} [options]
     * @param {string} [options.providerId] Filter by provider ID
     * @param {boolean} [options.activeOnly] Only return active models
     * @throws {EneoError}
     * */
    listTranscription: async (options) => {
      /** @type {any} */
      const fetchOptions = {
        method: "get",
        params: {
          query: {
            provider_id: options?.providerId,
            active_only: options?.activeOnly
          }
        }
      };
      const res = await client.fetch("/api/v1/admin/tenant-models/transcription/", fetchOptions);

      return res;
    },

    /**
     * Create a new Transcription Model.
     * @param {any} model
     * @throws {EneoError}
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
     * @throws {EneoError}
     * */
    updateTranscription: async ({ id }, update) => {
      const res = await client.fetch("/api/v1/admin/tenant-models/transcription/{model_id}/", {
        method: "put",
        params: { path: { model_id: id } },
        requestBody: {
          "application/json": update
        }
      });

      return res;
    },

    /**
     * Delete a Transcription Model.
     * @param {{id: string}} model
     * @throws {EneoError}
     * */
    deleteTranscription: async ({ id }) => {
      await client.fetch("/api/v1/admin/tenant-models/transcription/{model_id}/", {
        method: "delete",
        params: { path: { model_id: id } }
      });
    }
  };
}
