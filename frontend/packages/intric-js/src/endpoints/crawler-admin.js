/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').CrawlerRecentFailuresResponse} CrawlerRecentFailuresResponse */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initCrawlerAdmin(client) {
  return {
    /**
     * Get recent failed crawler runs for the current tenant.
     * @param {{days?: number, limit?: number, offset?: number}} [params]
     * @returns {Promise<CrawlerRecentFailuresResponse>}
     * @throws {IntricError}
     */
    recentFailures: async (params) => {
      const res = await client.fetch("/api/v1/admin/crawler/recent-failures", {
        method: "get",
        params: { query: params }
      });
      return res;
    }
  };
}
