/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').CrawlerActiveInventoryResponse} CrawlerActiveInventoryResponse */
/** @typedef {import('../types/resources').CrawlerTenantFailureInventoryResponse} CrawlerTenantFailureInventoryResponse */
/** @typedef {import('../types/resources').CrawlerRecentFailuresResponse} CrawlerRecentFailuresResponse */
/** @typedef {import('../types/resources').CrawlerScheduledAggregateResponse} CrawlerScheduledAggregateResponse */
/** @typedef {import('../types/resources').CrawlerTenantWebsiteProcessingAggregateResponse} CrawlerTenantWebsiteProcessingAggregateResponse */
/** @typedef {import('../types/schema').components["schemas"]["CrawlerTenantWebsiteInventoryResponse"]} CrawlerTenantWebsiteInventoryResponse */
/** @typedef {import('../types/schema').components["schemas"]["CrawlerTenantWebsiteInventorySort"]} CrawlerTenantWebsiteInventorySort */
/** @typedef {import('../types/schema').components["schemas"]["CrawlerFailureState"]} CrawlerFailureState */
/** @typedef {import('../types/schema').components["schemas"]["UpdateInterval"]} CrawlerUpdateInterval */
/** @typedef {import('../types/schema').components["schemas"]["CrawlerBulkIntervalResponse"]} CrawlerBulkIntervalResponse */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initCrawlerAdmin(client) {
  return {
    /**
     * Get active and queued crawler runs for the current tenant.
     * Pass `website_id` to scope the lookup to one website (used by
     * the detail Dialog's abort-affordance gating).
     * @param {{limit?: number, offset?: number, lifecycle_status?: import('../types/schema').components["schemas"]["CrawlLifecycle"], website_id?: string}} [params]
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
     * @param {{days?: number, limit?: number, offset?: number, website_id?: string}} [params]
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
    },

    /**
     * Queue an immediate crawl retry for one website in the current tenant.
     * Re-queues a fresh crawl via the existing CrawlService.crawl path
     * without touching circuit-breaker counters or the update_interval.
     * @param {string} websiteId
     * @returns {Promise<void>}
     * @throws {IntricError}
     */
    retryCrawl: async (websiteId) => {
      await client.fetch("/api/v1/admin/crawler/websites/{website_id}/retry", {
        method: "post",
        params: { path: { website_id: websiteId } }
      });
    },

    /**
     * List every website in the current tenant with consolidated governance
     * attribution (space, collection, owner email, schedule, failure state).
     * Powers the Webbplatser admin tab — search by URL/name/owner, filter by
     * interval/space/owner/failure-state, sort, paginate. Tenant scope is
     * implicit (`current_user.tenant_id` on the backend); admin role required.
     * @param {{
     *   limit?: number,
     *   offset?: number,
     *   search?: string,
     *   update_interval?: CrawlerUpdateInterval,
     *   space_id?: string,
     *   owner_user_id?: string,
     *   failure_state?: CrawlerFailureState,
     *   sort?: CrawlerTenantWebsiteInventorySort
     * }} [params]
     * @returns {Promise<CrawlerTenantWebsiteInventoryResponse>}
     * @throws {IntricError}
     */
    tenantWebsiteInventory: async (params) => {
      const res = await client.fetch("/api/v1/admin/crawler/websites", {
        method: "get",
        params: { query: params }
      });
      return res;
    },

    /**
     * Hard-delete one website from the current tenant. Tenant-scoped on
     * the backend; 404 for unknown id or cross-tenant; 409 with
     * `error_code=ACTIVE_JOB_BLOCKING` when a queued/running crawl is
     * attached (operator must abort it first). On success the cascade
     * removes crawl_runs, websites_spaces, assistants_websites, and
     * info_blobs in one transaction.
     * @param {string} websiteId
     * @returns {Promise<void>}
     * @throws {IntricError}
     */
    deleteWebsite: async (websiteId) => {
      await client.fetch("/api/v1/admin/crawler/websites/{website_id}", {
        method: "delete",
        params: { path: { website_id: websiteId } }
      });
    },

    /**
     * Apply one update_interval to many websites in the current tenant.
     * Capped at 100 explicit ids per request (the request body cap
     * lives in `BULK_INTERVAL_MAX_WEBSITE_IDS`). Each per-row outcome
     * is one of:
     *   - applied: the row's interval changed; metadata mirrors the
     *     per-row endpoint shape so audit consumers stay consistent
     *   - unchanged: the row already had the target interval; no-op
     *   - failed: the row wasn't found in the tenant (deleted
     *     concurrently or cross-tenant id guess)
     * Each `applied` row emits the same per-website audit row as the
     * per-row endpoint, so audit-log search by EntityType.WEBSITE
     * entity_id remains intact. Returns 200 with a typed structured
     * payload (not 207) — the SDK consumer can render a partial-
     * success summary and drill into failures by id.
     * @param {string[]} websiteIds
     * @param {CrawlerUpdateInterval} updateInterval
     * @returns {Promise<CrawlerBulkIntervalResponse>}
     * @throws {IntricError}
     */
    bulkSetUpdateInterval: async (websiteIds, updateInterval) => {
      const res = await client.fetch("/api/v1/admin/crawler/websites/bulk-interval", {
        method: "post",
        requestBody: {
          "application/json": {
            website_ids: websiteIds,
            update_interval: updateInterval
          }
        }
      });
      return res;
    }
  };
}
