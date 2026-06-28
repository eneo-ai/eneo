/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initLogging(client) {
  return {
    /**
     * Get logging info of a specific message by id
     * @param {{id: string}} message Message to get detailed logs of
     * @throws {EneoError}
     * */
    get: async (message) => {
      const { id } = message;
      const res = await client.fetch("/api/v1/logging/{message_id}/", {
        method: "get",
        params: {
          path: { message_id: id }
        }
      });
      return res;
    }
  };
}
