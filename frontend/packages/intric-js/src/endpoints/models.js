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
    }
  };
}
