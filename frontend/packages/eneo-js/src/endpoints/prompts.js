/** @typedef {import('../types/resources').Prompt} Prompt */
/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initPrompts(client) {
  return {
    /**
     * Get a specific prompt
     * @param {{id: string}} prompt
     * @returns {Promise<Prompt>}
     */
    get: async (prompt) => {
      const { id } = prompt;
      const res = await client.fetch("/api/v1/prompts/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Update prompt description
     * @param {Object} params
     * @param {{id: string}} params.prompt
     * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/prompts/{id}/">} params.update
     * @returns {Promise<Prompt>}
     * @throws {EneoError}
     */
    update: async ({ prompt, update }) => {
      const { id } = prompt;
      const res = await client.fetch("/api/v1/prompts/{id}/", {
        method: "patch",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Delete a specific prompt
     * @param {{id: string}} prompt
     * @returns status 204 on success; should throw on error
     * @throws {EneoError}
     */
    delete: async (prompt) => {
      const { id } = prompt;
      const res = await client.fetch("/api/v1/prompts/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    }
  };
}
