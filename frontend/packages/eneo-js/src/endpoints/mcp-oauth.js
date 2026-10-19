/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/schema').components["schemas"]["MCPOAuthConnectionPublic"]} MCPOAuthConnection */

/**
 * Eneo as an OAuth client toward MCP servers: the per-user (or shared)
 * connect flow and the caller's connection state.
 *
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initMcpOauth(client) {
  return {
    /**
     * Start authorizing Eneo at an OAuth MCP server's authorization server.
     * Returns the URL to open in a popup and the state the callback must echo.
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @returns {Promise<{url: string; state: string}>}
     * @throws {EneoError}
     */
    authorizeUrl: async ({ id }) => {
      return await client.fetch("/api/v1/mcp-oauth/servers/{id}/authorize-url/", {
        method: "post",
        params: { path: { id } }
      });
    },

    /**
     * Finish an authorization with the code the popup received.
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @param {string} params.code
     * @param {string} params.state
     * @param {string | null} [params.iss] The issuer echoed in the redirect (RFC 9207), when present
     * @returns {Promise<MCPOAuthConnection>}
     * @throws {EneoError}
     */
    completeCallback: async ({ id, code, state, iss }) => {
      return await client.fetch("/api/v1/mcp-oauth/servers/{id}/callback/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": { code, state, iss: iss ?? null } }
      });
    },

    /**
     * Tell a turn paused on this authorization to stop waiting: the user
     * refused or abandoned the vendor's consent page.
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @throws {EneoError}
     */
    decline: async ({ id }) => {
      await client.fetch("/api/v1/mcp-oauth/servers/{id}/decline/", {
        method: "post",
        params: { path: { id } }
      });
      return true;
    },

    /**
     * Forget the caller's connection to a server (revoking its tokens when possible).
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @throws {EneoError}
     */
    disconnect: async ({ id }) => {
      await client.fetch("/api/v1/mcp-oauth/servers/{id}/connection/", {
        method: "delete",
        params: { path: { id } }
      });
      return true;
    },

    /**
     * The caller's state at every OAuth MCP server of the tenant.
     * @returns {Promise<MCPOAuthConnection[]>}
     * @throws {EneoError}
     */
    myConnections: async () => {
      const res = await client.fetch("/api/v1/mcp-oauth/connections/", { method: "get" });
      return res.items;
    },

    /**
     * The caller's state at the OAuth servers a turn of this assistant reaches.
     * @param {Object} params
     * @param {string} params.assistantId
     * @returns {Promise<MCPOAuthConnection[]>}
     * @throws {EneoError}
     */
    assistantConnections: async ({ assistantId }) => {
      const res = await client.fetch("/api/v1/mcp-oauth/assistants/{id}/connections/", {
        method: "get",
        params: { path: { id: assistantId } }
      });
      return res.items;
    }
  };
}
