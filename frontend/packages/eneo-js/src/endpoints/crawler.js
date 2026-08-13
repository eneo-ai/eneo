/**
 * @param {import('../client/client').Client} client
 */
export function initCrawler(client) {
  return {
    /** Get tenant-scoped native crawler diagnostics and configured probe targets. */
    diagnostics: async () => {
      return client.fetch("/api/v1/crawler/diagnostics/", { method: "get" });
    },

    /**
     * Run a bounded, audited probe against one configured website.
     * @param {string} websiteId
     */
    probe: async (websiteId) => {
      return client.fetch("/api/v1/crawler/diagnostics/{website_id}/probe/", {
        method: "post",
        params: { path: { website_id: websiteId } }
      });
    }
  };
}
