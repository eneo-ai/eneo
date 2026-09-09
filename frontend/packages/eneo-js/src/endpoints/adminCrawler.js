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

    /** @param {{id: string, limit?: number, cursor?: string | null}} options */
    failures: async ({ id, limit = 100, cursor }) =>
      client.fetch("/api/v1/admin/crawler/runs/{id}/failures/", {
        method: "get",
        params: { path: { id }, query: { limit, cursor } }
      })
  };
}
