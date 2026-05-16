/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').CrawlerActiveInventoryResponse} CrawlerActiveInventoryResponse */
/** @typedef {import('../types/resources').CrawlerTenantFailureInventoryResponse} CrawlerTenantFailureInventoryResponse */
/** @typedef {import('../types/resources').CrawlerRecentFailuresResponse} CrawlerRecentFailuresResponse */
/** @typedef {import('../types/resources').CrawlerScheduledAggregateResponse} CrawlerScheduledAggregateResponse */
/** @typedef {import('../types/resources').CrawlerTenantWebsiteProcessingAggregateResponse} CrawlerTenantWebsiteProcessingAggregateResponse */
/** @typedef {import('../types/schema').components["schemas"]["UpdateInterval"]} CrawlerUpdateInterval */

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
     * Get crawler websites currently backed off or disabled for the current tenant.
     * @param {{limit?: number, offset?: number}} [params]
     * @returns {Promise<CrawlerTenantFailureInventoryResponse>}
     * @throws {IntricError}
     */
    failureInventory: async (params) => {
      const res = await client.fetch("/api/v1/admin/crawler/failure-inventory", {
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
     * Get recent crawler runs stopped by lifecycle protection for the current tenant.
     * @param {{days?: number, limit?: number, offset?: number}} [params]
     * @returns {Promise<CrawlerRecentFailuresResponse>}
     * @throws {IntricError}
     */
    watchdogInterventions: async (params) => {
      const res = await client.fetch("/api/v1/admin/crawler/watchdog-interventions", {
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
     * Get crawler processing totals grouped by website for the current tenant.
     * @param {{days?: number, limit?: number, offset?: number}} [params]
     * @returns {Promise<CrawlerTenantWebsiteProcessingAggregateResponse>}
     * @throws {IntricError}
     */
    websiteProcessingAggregate: async (params) => {
      const res = await client.fetch("/api/v1/admin/crawler/website-processing", {
        method: "get",
        params: { query: params }
      });
      return res;
    },

    /**
     * Abort a queued or running crawler job for the current tenant. The backend
     * commits a terminal CRAWL_ABORTED event the worker observes via its
     * heartbeat preemption check.
     * @param {string} jobId
     * @returns {Promise<void>}
     * @throws {IntricError}
     */
    abortCrawl: async (jobId) => {
      await client.fetch("/api/v1/admin/crawler/jobs/{job_id}/abort", {
        method: "post",
        params: { path: { job_id: jobId } }
      });
    },

    /**
     * Reset crawler circuit breaker counters for one website in the current tenant.
     * Clears consecutive_failures and next_retry_at without touching update_interval.
     * @param {string} websiteId
     * @returns {Promise<void>}
     * @throws {IntricError}
     */
    resetCircuitBreaker: async (websiteId) => {
      await client.fetch("/api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker", {
        method: "post",
        params: { path: { website_id: websiteId } }
      });
    },

    /**
     * Change the scheduled crawl interval for one website in the current tenant.
     * Setting `never` pauses the recurring schedule; any other value resumes it.
     * @param {string} websiteId
     * @param {CrawlerUpdateInterval} updateInterval
     * @returns {Promise<void>}
     * @throws {IntricError}
     */
    setUpdateInterval: async (websiteId, updateInterval) => {
      await client.fetch("/api/v1/admin/crawler/websites/{website_id}/update-interval", {
        method: "patch",
        params: { path: { website_id: websiteId } },
        requestBody: {
          "application/json": {
            update_interval: updateInterval
          }
        }
      });
    }
  };
}
