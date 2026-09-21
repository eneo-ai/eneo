/** @param {import('../client/client').Client} client */
export function initAdminCrawler(client) {
  return {
    /**
     * Read a bounded page of tenant crawl metadata. Requires admin permission.
     * @param {import('../types/resources').AdminCrawlerQuery} [query]
     */
    overview: async (query = {}) =>
      client.fetch("/api/v1/admin/crawler/", {
        method: "get",
        params: { query }
      }),

    /** @param {{id: string}} run */
    details: async ({ id }) =>
      client.fetch("/api/v1/admin/crawler/runs/{id}/", {
        method: "get",
        params: { path: { id } }
      }),

    /** @param {{id: string, limit?: number, cursor?: string | null}} options */
    history: async ({ id, limit = 10, cursor }) =>
      client.fetch("/api/v1/admin/crawler/websites/{id}/runs/", {
        method: "get",
        params: { path: { id }, query: { limit, cursor } }
      }),

    /** @param {{id: string, limit?: number, cursor?: string | null}} options */
    matches: async ({ id, limit = 10, cursor }) =>
      client.fetch("/api/v1/admin/crawler/websites/{id}/matches/", {
        method: "get",
        params: { path: { id }, query: { limit, cursor } }
      }),

    /** @param {{id: string}} website */
    start: async ({ id }) =>
      client.fetch("/api/v1/admin/crawler/websites/{id}/run/", {
        method: "post",
        params: { path: { id } }
      }),

    /** @param {{id: string}} run */
    cancel: async ({ id }) =>
      client.fetch("/api/v1/admin/crawler/runs/{id}/cancel/", {
        method: "post",
        params: { path: { id } }
      }),

    /** @param {import('../types/resources').CrawlFailureQuery} options */
    failures: async ({ id, limit = 100, cursor, kind }) =>
      client.fetch("/api/v1/admin/crawler/runs/{id}/failures/", {
        method: "get",
        params: { path: { id }, query: { limit, cursor, kind } }
      })
  };
}
