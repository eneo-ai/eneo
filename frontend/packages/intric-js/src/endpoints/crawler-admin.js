/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').CrawlerActiveInventoryResponse} CrawlerActiveInventoryResponse */
/** @typedef {import('../types/resources').CrawlerRecentFailuresResponse} CrawlerRecentFailuresResponse */
/** @typedef {import('../types/resources').CrawlerScheduledAggregateResponse} CrawlerScheduledAggregateResponse */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initCrawlerAdmin(client) {
  return {
    /**
     * Get active and queued crawler runs for the current tenant.
     * @param {{limit?: number, offset?: number}} [params]
     * @returns {Promise<CrawlerActiveInventoryResponse>}
     * @throws {IntricError}
     */
    activeInventory: async (params) => {
      const res = await client.fetch("/api/v1/admin/crawler/active", {
        method: "get",
        params: { query: params }
      });
      return res;
    },

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
    },

    /**
     * Get scheduled crawler load grouped by update interval for the current tenant.
     * @returns {Promise<CrawlerScheduledAggregateResponse>}
     * @throws {IntricError}
     */
    scheduledAggregate: async () => {
      const res = await client.fetch("/api/v1/admin/crawler/scheduled", {
        method: "get"
      });
      return res;
    },

    /**
     * Abort a queued crawler job for the current tenant.
     * @param {string} jobId
     * @returns {Promise<void>}
     * @throws {IntricError}
     */
    abortQueuedJob: async (jobId) => {
      await client.fetch("/api/v1/admin/crawler/jobs/{job_id}/abort", {
        method: "post",
        params: { path: { job_id: jobId } }
      });
    }
  };
}
