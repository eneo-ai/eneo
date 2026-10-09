/** @typedef {import('../types/resources').TranscriptionService} TranscriptionService */
/** @typedef {import('../types/resources').TranscriptionServiceSummary} TranscriptionServiceSummary */
/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initTranscriptionServices(client) {
  /**
   * @param {{limit?: number, offset?: number}} [params]
   * @returns {Promise<{items: TranscriptionService[], has_more: boolean}>}
   */
  const list = async ({ limit, offset } = {}) => {
    return await client.fetch("/api/v1/admin/transcription-services/", {
      method: "get",
      params: { query: { limit, offset } }
    });
  };

  /**
   * @param {{limit?: number, offset?: number}} [params]
   * @returns {Promise<{items: TranscriptionServiceSummary[], has_more: boolean}>}
   */
  const listCatalogue = async ({ limit, offset } = {}) => {
    return await client.fetch("/api/v1/transcription-services/", {
      method: "get",
      params: { query: { limit, offset } }
    });
  };

  return {
    /**
     * List one page of the organisation's speaker identification services with
     * their addresses. Requires the admin permission; keys are never returned.
     * @param {{limit?: number, offset?: number}} [params]
     * @throws {EneoError}
     * @returns {Promise<{items: TranscriptionService[], has_more: boolean}>}
     */
    list,

    /**
     * Get one speaker identification service.
     * @param {{id: string}} service
     * @throws {EneoError}
     * @returns {Promise<TranscriptionService>}
     */
    get: async ({ id }) => {
      return await client.fetch("/api/v1/admin/transcription-services/{connection_id}/", {
        method: "get",
        params: { path: { connection_id: id } }
      });
    },

    /**
     * Connect a speaker identification service. The API key is write-only.
     * @param {import('../types/resources').TranscriptionServiceCreate} service
     * @throws {EneoError} 409 when the name is taken
     * @returns {Promise<TranscriptionService>}
     */
    create: async (service) => {
      return await client.fetch("/api/v1/admin/transcription-services/", {
        method: "post",
        requestBody: { "application/json": service }
      });
    },

    /**
     * Change the fields sent. Moving the endpoint needs a new `api_key` in the
     * same request; `security_classification: null` clears the classification.
     * @param {{id: string}} service
     * @param {import('../types/resources').TranscriptionServiceUpdate} update
     * @throws {EneoError}
     * @returns {Promise<TranscriptionService>}
     */
    update: async ({ id }, update) => {
      return await client.fetch("/api/v1/admin/transcription-services/{connection_id}/", {
        method: "patch",
        params: { path: { connection_id: id } },
        requestBody: { "application/json": update }
      });
    },

    /**
     * Remove a speaker identification service and its space grants.
     * @param {{id: string}} service
     * @throws {EneoError}
     * @returns {Promise<void>}
     */
    delete: async ({ id }) => {
      await client.fetch("/api/v1/admin/transcription-services/{connection_id}/", {
        method: "delete",
        params: { path: { connection_id: id } }
      });
    },

    /**
     * Ask the service whether it would accept a job with the saved settings.
     * Sends no audio and starts no job.
     * @param {{id: string}} service
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').TranscriptionServiceCheck>}
     */
    check: async ({ id }) => {
      return await client.fetch("/api/v1/admin/transcription-services/{connection_id}/check/", {
        method: "post",
        params: { path: { connection_id: id } }
      });
    },

    /**
     * List one page of the services by name, without addresses or keys, for
     * granting them to spaces. Any signed-in user may read it.
     * @param {{limit?: number, offset?: number}} [params]
     * @throws {EneoError}
     * @returns {Promise<{items: TranscriptionServiceSummary[], has_more: boolean}>}
     */
    listCatalogue
  };
}
