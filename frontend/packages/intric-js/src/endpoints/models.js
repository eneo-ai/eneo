/** @typedef {import('../types/resources').CompletionModel} CompletionModel */
/** @typedef {import('../types/resources').EmbeddingModel} EmbeddingModel */
/** @typedef {import('../types/resources').TranscriptionModel} TranscriptionModel */
/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initModels(client) {
  return {
    /**
     * List all Models.
     * @param {Object} [options]
     * @param {{id: string}} [options.space] Get models based on a space and its security classification
     * @throws {IntricError}
     * */
    list: async (options) => {
      const res = await client.fetch("/api/v1/ai-models/", {
        method: "get",
        params: {
          query: options?.space ? { space_id: options.space.id } : undefined
        }
      });

      return {
        completionModels: res.completion_models,
        embeddingModels: res.embedding_models,
        transcriptionModels: res.transcription_models
      };
    },

    /**
     * Update either an existing Completion Model, Embedding Model, or Transcription Model, only one can be processed at any time
     * @template {{completionModel: {id:string}, embeddingModel?: never, transcriptionModel?: never, update:import('../types/fetch').JSONRequestBody<"post", "/api/v1/completion-models/{id}/">} | {completionModel?: never, embeddingModel: {id:string}, transcriptionModel?: never, update:import('../types/fetch').JSONRequestBody<"post", "/api/v1/embedding-models/{id}/">} | {completionModel?: never, embeddingModel?: never, transcriptionModel: {id:string}, update:import('../types/fetch').JSONRequestBody<"post", "/api/v1/transcription-models/{id}/">}} T
     * @param {T} params
     * @returns {Promise<T extends { completionModel: { id: string } } ? CompletionModel : T extends { embeddingModel: { id: string } } ? EmbeddingModel : TranscriptionModel>}
     * @throws {IntricError}
     * */
    update: async ({ completionModel, embeddingModel, transcriptionModel, update }) => {
      if (completionModel) {
        const { id } = completionModel;
        const res = await client.fetch("/api/v1/completion-models/{id}/", {
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": update }
        });
        /** @ts-expect-error Jsdoc can't properly infer return type */
        return res;
      } else if (embeddingModel) {
        const { id } = embeddingModel;
        const res = await client.fetch("/api/v1/embedding-models/{id}/", {
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": update }
        });
        /** @ts-expect-error Jsdoc can't properly infer return type */
        return res;
      } else {
        const { id } = transcriptionModel;
        const res = await client.fetch("/api/v1/transcription-models/{id}/", {
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": update }
        });
        /** @ts-expect-error Jsdoc can't properly infer return type */
        return res;
      }
    },

    /**
     * Validate migration compatibility without executing.
     * @param {Object} params
     * @param {string} params.fromId Source model ID
     * @param {string} params.toId Target model ID
     * @returns {Promise<import("../types/schema").components["schemas"]["ValidationResult"]>}
     * @throws {IntricError}
     * */
    validateMigration: async ({ fromId, toId }) => {
      const res = await client.fetch("/api/v1/completion-models/{model_id}/migration-validate", {
        method: "get",
        params: {
          path: { model_id: fromId },
          query: { to_model_id: toId }
        }
      });

      return res;
    },

    /**
     * Migrate completion model usage to another model.
     * @param {Object} params
     * @param {string} params.fromId Source model ID
     * @param {string} params.toId Target model ID
     * @param {string[]} [params.entityTypes] Optional list of entity types to migrate
     * @param {boolean} [params.confirmMigration] Proceed even if compatibility warnings exist
     * @returns {Promise<import("../types/schema").components["schemas"]["MigrationResult"]>}
     * @throws {IntricError}
     * */
    migrateCompletion: async ({ fromId, toId, entityTypes, confirmMigration }) => {
      const res = await client.fetch("/api/v1/completion-models/{model_id}/migrate", {
        method: "post",
        params: { path: { model_id: fromId } },
        requestBody: {
          "application/json": {
            to_model_id: toId,
            entity_types: entityTypes,
            confirm_migration: confirmMigration
          }
        }
      });

      return res;
    },

    /**
     * Get usage statistics for a completion model (aggregated counts).
     * @param {Object} params
     * @param {string} params.modelId Model ID
     * @returns {Promise<import("../types/schema").components["schemas"]["ModelUsageStatistics"]>}
     * @throws {IntricError}
     * */
    getUsageStats: async ({ modelId }) => {
      const res = await client.fetch("/api/v1/completion-models/{model_id}/usage", {
        method: "get",
        params: { path: { model_id: modelId } }
      });

      return res;
    },

    /**
     * Get detailed usage for a completion model (individual entities).
     * @param {Object} params
     * @param {string} params.modelId Model ID
     * @param {string} [params.entityType] Filter by entity type
     * @param {number} [params.limit=50] Number of results
     * @returns {Promise<import("../types/schema").components["schemas"]["PaginatedResponse"]>}
     * @throws {IntricError}
     * */
    getUsageDetails: async ({ modelId, entityType, limit = 50 }) => {
      /** @type {Record<string, any>} */
      const query = { limit };
      if (entityType) query.entity_type = entityType;

      const res = await client.fetch("/api/v1/completion-models/{model_id}/usage/details", {
        method: "get",
        params: {
          path: { model_id: modelId },
          // Query params are read via a custom Depends() on the backend, so
          // they don't appear in the OpenAPI schema's params type.
          // @ts-expect-error see comment above
          query
        }
      });

      return res;
    },

    /**
     * Get migration history for a specific completion model.
     * @param {Object} params
     * @param {string} params.modelId Model ID
     * @param {number} [params.limit=50] Number of results
     * @param {number} [params.offset=0] Offset for pagination
     * @returns {Promise<import("../types/schema").components["schemas"]["ModelMigrationHistory"][]>}
     * @throws {IntricError}
     * */
    getMigrationHistory: async ({ modelId, limit = 50, offset = 0 }) => {
      const res = await client.fetch("/api/v1/completion-models/{model_id}/migration-history", {
        method: "get",
        // Query params are read via a custom Depends() on the backend, so
        // they don't appear in the OpenAPI schema's params type.
        // @ts-expect-error see comment above
        params: { path: { model_id: modelId }, query: { limit, offset } }
      });

      return res;
    },

    /**
     * Get all migration history for the tenant.
     * @param {Object} [params]
     * @param {number} [params.limit=50] Number of results
     * @param {number} [params.offset=0] Offset for pagination
     * @returns {Promise<import("../types/schema").components["schemas"]["ModelMigrationHistory"][]>}
     * @throws {IntricError}
     * */
    getAllMigrationHistory: async ({ limit = 50, offset = 0 } = {}) => {
      const res = await client.fetch("/api/v1/completion-models/migration-history", {
        method: "get",
        // Query params are read via a custom Depends() on the backend, so
        // they don't appear in the OpenAPI schema's params type.
        // @ts-expect-error see comment above
        params: { query: { limit, offset } }
      });

      return res;
    },

    /**
     * Validate transcription migration compatibility without executing.
     * @param {Object} params
     * @param {string} params.fromId Source model ID
     * @param {string} params.toId Target model ID
     * @returns {Promise<import("../types/schema").components["schemas"]["ValidationResult"]>}
     * @throws {IntricError}
     * */
    validateTranscriptionMigration: async ({ fromId, toId }) => {
      const res = await client.fetch("/api/v1/transcription-models/{model_id}/migration-validate", {
        method: "get",
        params: {
          path: { model_id: fromId },
          query: { to_model_id: toId }
        }
      });

      return res;
    },

    /**
     * Migrate transcription model usage to another model.
     * @param {Object} params
     * @param {string} params.fromId Source model ID
     * @param {string} params.toId Target model ID
     * @param {string[]} [params.entityTypes] Optional list of entity types to migrate
     * @param {boolean} [params.confirmMigration] Proceed even if compatibility warnings exist
     * @returns {Promise<import("../types/schema").components["schemas"]["MigrationResult"]>}
     * @throws {IntricError}
     * */
    migrateTranscription: async ({ fromId, toId, entityTypes, confirmMigration }) => {
      const res = await client.fetch("/api/v1/transcription-models/{model_id}/migrate", {
        method: "post",
        params: { path: { model_id: fromId } },
        requestBody: {
          "application/json": {
            to_model_id: toId,
            entity_types: entityTypes,
            confirm_migration: confirmMigration
          }
        }
      });

      return res;
    },

    /**
     * Get migration history for a specific transcription model.
     * @param {Object} params
     * @param {string} params.modelId Model ID
     * @param {number} [params.limit=50] Number of results
     * @param {number} [params.offset=0] Offset for pagination
     * @returns {Promise<import("../types/schema").components["schemas"]["ModelMigrationHistory"][]>}
     * @throws {IntricError}
     * */
    getTranscriptionMigrationHistory: async ({ modelId, limit = 50, offset = 0 }) => {
      const res = await client.fetch("/api/v1/transcription-models/{model_id}/migration-history", {
        method: "get",
        params: { path: { model_id: modelId }, query: { limit, offset } }
      });

      return res;
    },

    /**
     * Get all transcription migration history for the tenant.
     * @param {Object} [params]
     * @param {number} [params.limit=50] Number of results
     * @param {number} [params.offset=0] Offset for pagination
     * @returns {Promise<import("../types/schema").components["schemas"]["ModelMigrationHistory"][]>}
     * @throws {IntricError}
     * */
    getAllTranscriptionMigrationHistory: async ({ limit = 50, offset = 0 } = {}) => {
      const res = await client.fetch("/api/v1/transcription-models/migration-history", {
        method: "get",
        params: { query: { limit, offset } }
      });

      return res;
    },

    /**
     * Get migration impact counts (apps + spaces) for a transcription model.
     * @param {Object} params
     * @param {string} params.modelId Model ID
     * @returns {Promise<import("../types/schema").components["schemas"]["TranscriptionModelUsageStats"]>}
     * @throws {IntricError}
     * */
    getTranscriptionUsageStats: async ({ modelId }) => {
      const res = await client.fetch("/api/v1/transcription-models/{model_id}/usage", {
        method: "get",
        params: { path: { model_id: modelId } }
      });

      return res;
    },

    /**
     * Get detailed usage (apps) for a transcription model. Mirrors
     * getUsageDetails so the migrate dialog renders both with one component.
     * @param {Object} params
     * @param {string} params.modelId Model ID
     * @param {number} [params.limit=100] Number of results
     * @returns {Promise<import("../types/schema").components["schemas"]["TranscriptionModelUsageDetails"]>}
     * @throws {IntricError}
     * */
    getTranscriptionUsageDetails: async ({ modelId, limit = 100 }) => {
      const res = await client.fetch("/api/v1/transcription-models/{model_id}/usage/details", {
        method: "get",
        params: { path: { model_id: modelId }, query: { limit } }
      });

      return res;
    }
  };
}
