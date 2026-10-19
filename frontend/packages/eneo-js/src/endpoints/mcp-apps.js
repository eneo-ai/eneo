/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initMcpApps(client) {
  return {
    /**
     * Get approved MCP App HTML and a signed URL for its trusted sandbox.
     * Unlike file signed URLs, the returned URL is NOT rebased onto the
     * client's base URL: it points at the dedicated content origin, which is
     * the browser isolation boundary for app iframes.
     * @param {Object} params
     * @param {string} params.viewId The MCP App view ID (from the tool reference meta)
     * @returns {Promise<{url: string, expires_at: number, html: string}>}
     * @throws {EneoError}
     * */
    mintViewToken: async ({ viewId }) => {
      return await client.fetch("/api/v1/mcp-apps/views/{view_id}/token/", {
        method: "post",
        params: { path: { view_id: viewId } }
      });
    }
  };
}
