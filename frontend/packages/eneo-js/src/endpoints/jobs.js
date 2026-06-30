/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').Job} Job */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initJobs(client) {
  return {
    /**
     * List all jobs.
     * @returns {Promise<Job[]>}
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/jobs/", {
        method: "get"
      });
      return res.items;
    },

    /**
     * Get info of a job via its id.
     * @param  {{id: string} | Job} job job
     * @returns {Promise<Job>} Current info about the queried job
     * @throws {EneoError}
     * */
    get: async (job) => {
      const { id } = job;
      const res = await client.fetch("/api/v1/jobs/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    }
  };
}
