/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 * @throws {EneoError}
 */
export function initDashboard(client) {
  return {
    /**
     * List all assistants on the users Dashboard
     * @returns {Promise<import('../types/resources').Dashboard>}
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/dashboard/", {
        method: "get",
        params: {
          query: {
            only_published: false
          }
        }
      });
      return res;
    }
  };
}
