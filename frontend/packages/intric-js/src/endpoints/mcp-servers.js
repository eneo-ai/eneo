/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initMCPServers(client) {
  return {
    /**
     * Lists all MCP servers from the global catalog (admin only).
     * @param {Object} [params]
     * @param {string[]} [params.tags] Optional tags to filter by
     * @throws {IntricError}
     * */
    list: async (params = {}) => {
      const res = await client.fetch("/api/v1/mcp-servers/", {
        method: "get",
        params: {
          query: params.tags ? { tags: params.tags } : undefined
        }
      });
      return res;
    },

    /**
     * Get a single MCP server by ID (admin only).
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @throws {IntricError}
     * */
    get: async ({ id }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{id}/", {
        method: "get",
        params: {
          path: { id }
        }
      });
      return res;
    },

    /**
     * Create a new MCP server in the global catalog (admin only, HTTP-only).
     * @param {Object} params
     * @param {string} params.name Name of the MCP server
     * @param {string} params.http_url HTTP URL to the MCP server
     * @param {"sse" | "streamable_http"} [params.transport_type] Transport type (default: sse)
     * @param {"none" | "bearer" | "api_key" | "custom_headers"} [params.http_auth_type] Authentication type (default: none)
     * @param {string} [params.description] Description
     * @param {Object} [params.http_auth_config_schema] Authentication configuration
     * @param {Object} [params.config_schema] JSON schema for configuration
     * @param {string[]} [params.tags] Tags for categorization
     * @param {string} [params.icon_url] URL to icon image
     * @param {string} [params.documentation_url] URL to documentation
     * @throws {IntricError}
     * */
    create: async ({
      name,
      http_url,
      transport_type,
      http_auth_type,
      description,
      http_auth_config_schema,
      config_schema,
      tags,
      icon_url,
      documentation_url
    }) => {
      const res = await client.fetch("/api/v1/mcp-servers/", {
        method: "post",
        requestBody: {
          "application/json": {
            name,
            http_url,
            transport_type,
            http_auth_type,
            description,
            http_auth_config_schema,
            config_schema,
            tags,
            icon_url,
            documentation_url
          }
        }
      });
      return res;
    },

    /**
     * Update an MCP server in the global catalog (admin only, HTTP-only).
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @param {string} [params.name] Name of the MCP server
     * @param {string} [params.http_url] HTTP URL to the MCP server
     * @param {"sse" | "streamable_http"} [params.transport_type] Transport type
     * @param {"none" | "bearer" | "api_key" | "custom_headers"} [params.http_auth_type] Authentication type
     * @param {string} [params.description] Description
     * @param {Object} [params.http_auth_config_schema] Authentication configuration
     * @param {Object} [params.config_schema] JSON schema for configuration
     * @param {string[]} [params.tags] Tags for categorization
     * @param {string} [params.icon_url] URL to icon image
     * @param {string} [params.documentation_url] URL to documentation
     * @throws {IntricError}
     * */
    update: async ({
      id,
      name,
      http_url,
      transport_type,
      http_auth_type,
      description,
      http_auth_config_schema,
      config_schema,
      tags,
      icon_url,
      documentation_url
    }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{id}/", {
        method: "post",
        params: {
          path: { id }
        },
        requestBody: {
          "application/json": {
            name,
            http_url,
            transport_type,
            http_auth_type,
            description,
            http_auth_config_schema,
            config_schema,
            tags,
            icon_url,
            documentation_url
          }
        }
      });
      return res;
    },

    /**
     * Delete an MCP server from the global catalog (admin only).
     * @param {Object} params
     * @param {string} params.id The MCP server ID
     * @throws {IntricError}
     * */
    delete: async ({ id }) => {
      await client.fetch("/api/v1/mcp-servers/{id}/", {
        method: "delete",
        params: {
          path: { id }
        }
      });
    },

    /**
     * Get all available MCP servers with tenant enablement status.
     * Shows both enabled and disabled MCPs for the current tenant.
     * @throws {IntricError}
     * */
    listSettings: async () => {
      const res = await client.fetch("/api/v1/mcp-servers/settings/", {
        method: "get"
      });
      return res;
    },

    /**
     * Enable an MCP server for the current tenant.
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID to enable
     * @param {Object} [params.env_vars] Environment variables/credentials for this MCP
     * @throws {IntricError}
     * */
    enable: async ({ mcp_server_id, env_vars }) => {
      const res = await client.fetch("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
        method: "post",
        params: {
          path: { mcp_server_id }
        },
        requestBody: {
          "application/json": {
            env_vars
          }
        }
      });
      return res;
    },

    /**
     * Update MCP server settings for the current tenant.
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @param {boolean} [params.is_org_enabled] Enable/disable the MCP
     * @param {Object} [params.env_vars] Environment variables/credentials
     * @throws {IntricError}
     * */
    updateSettings: async ({ mcp_server_id, is_org_enabled, env_vars }) => {
      const res = await client.fetch("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
        method: "put",
        params: {
          path: { mcp_server_id }
        },
        requestBody: {
          "application/json": {
            is_org_enabled,
            env_vars
          }
        }
      });
      return res;
    },

    /**
     * Disable an MCP server for the current tenant.
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID to disable
     * @throws {IntricError}
     * */
    disable: async ({ mcp_server_id }) => {
      await client.fetch("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
        method: "delete",
        params: {
          path: { mcp_server_id }
        }
      });
    },

    /**
     * Get all tools for an MCP server.
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @throws {IntricError}
     * */
    listTools: async ({ mcp_server_id }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{mcp_server_id}/tools/", {
        method: "get",
        params: {
          path: { mcp_server_id }
        }
      });
      return res;
    },

    /**
     * Manually refresh/sync tools for an MCP server (admin only).
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @throws {IntricError}
     * */
    syncTools: async ({ mcp_server_id }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{mcp_server_id}/tools/sync/", {
        method: "post",
        params: {
          path: { mcp_server_id }
        }
      });
      return res;
    },

    /**
     * Update global default enabled status for a tool (admin only).
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @param {string} params.tool_id The tool ID
     * @param {boolean} params.is_enabled Whether tool should be enabled by default
     * @throws {IntricError}
     * */
    updateToolEnabled: async ({ mcp_server_id, tool_id, is_enabled }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{mcp_server_id}/tools/{tool_id}/", {
        method: "put",
        params: {
          path: { mcp_server_id, tool_id }
        },
        requestBody: {
          "application/json": {
            is_enabled
          }
        }
      });
      return res;
    },

    /**
     * Update tenant-level enablement for a tool (admin only).
     * Creates or updates a record in mcp_server_tool_settings.
     * @param {Object} params
     * @param {string} params.tool_id The tool ID
     * @param {boolean} params.is_enabled Whether tool should be enabled for this tenant
     * @throws {IntricError}
     * */
    updateTenantToolEnabled: async ({ tool_id, is_enabled }) => {
      const res = await client.fetch("/api/v1/mcp-servers/settings/tools/{tool_id}/", {
        method: "put",
        params: {
          path: { tool_id }
        },
        requestBody: {
          "application/json": {
            is_enabled
          }
        }
      });
      return res;
    }
  };
}
