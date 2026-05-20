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
     * @param {"none" | "bearer"} [params.http_auth_type] Authentication type (default: none)
     * @param {string} [params.description] Description
     * @param {{[key: string]: unknown} | null} [params.http_auth_config_schema] Authentication configuration
     * @param {{[key: string]: unknown} | null} [params.config_schema] JSON schema for configuration
     * @param {string[]} [params.tags] Tags for categorization
     * @param {string} [params.icon_url] URL to icon image
     * @param {string} [params.documentation_url] URL to documentation
     * @param {{id: string} | null} [params.security_classification] Security classification
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
      documentation_url,
      security_classification
    }) => {
      /** @type {any} */
      const body = {
        name,
        http_url,
        transport_type,
        http_auth_type,
        description,
        http_auth_config_schema,
        config_schema,
        tags,
        icon_url,
        documentation_url,
        security_classification
      };
      const res = await client.fetch("/api/v1/mcp-servers/", {
        method: "post",
        requestBody: {
          "application/json": body
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
     * @param {"none" | "bearer"} [params.http_auth_type] Authentication type
     * @param {string} [params.description] Description
     * @param {{[key: string]: unknown} | null} [params.http_auth_config_schema] Authentication configuration
     * @param {{[key: string]: unknown} | null} [params.config_schema] JSON schema for configuration
     * @param {string[]} [params.tags] Tags for categorization
     * @param {string} [params.icon_url] URL to icon image
     * @param {string} [params.documentation_url] URL to documentation
     * @param {{id: string} | null} [params.security_classification] Security classification
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
      documentation_url,
      security_classification
    }) => {
      /** @type {any} */
      const body = {
        name,
        http_url,
        transport_type,
        http_auth_type,
        description,
        http_auth_config_schema,
        config_schema,
        tags,
        icon_url,
        documentation_url,
        security_classification
      };
      const res = await client.fetch("/api/v1/mcp-servers/{id}/", {
        method: "post",
        params: {
          path: { id }
        },
        requestBody: {
          "application/json": body
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
     * @param {{[key: string]: unknown} | null} [params.env_vars] Environment variables/credentials for this MCP
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
     * @param {{[key: string]: unknown} | null} [params.env_vars] Environment variables/credentials
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
      const res = await client.fetch("/api/v1/mcp-servers/{id}/tools/", {
        method: "get",
        params: {
          path: { id: mcp_server_id }
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
      const res = await client.fetch("/api/v1/mcp-servers/{id}/tools/sync/", {
        method: "post",
        params: {
          path: { id: mcp_server_id }
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
      const res = await client.fetch("/api/v1/mcp-servers/{id}/tools/{tool_id}/", {
        method: "put",
        params: {
          path: { id: mcp_server_id, tool_id }
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
     * Approve pending tool changes (admin only).
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @param {string[]} params.tool_ids Tool IDs to approve
     * @throws {IntricError}
     * */
    approveToolChanges: async ({ mcp_server_id, tool_ids }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{id}/tools/review/approve/", {
        method: "post",
        params: { path: { id: mcp_server_id } },
        requestBody: { "application/json": { tool_ids } }
      });
      return res;
    },

    /**
     * Reject pending tool changes (admin only).
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @param {string[]} params.tool_ids Tool IDs to reject
     * @throws {IntricError}
     * */
    rejectToolChanges: async ({ mcp_server_id, tool_ids }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{id}/tools/review/reject/", {
        method: "post",
        params: { path: { id: mcp_server_id } },
        requestBody: { "application/json": { tool_ids } }
      });
      return res;
    },

    /**
     * Approve all pending tool changes (admin only).
     * @param {Object} params
     * @param {string} params.mcp_server_id The MCP server ID
     * @throws {IntricError}
     * */
    approveAllToolChanges: async ({ mcp_server_id }) => {
      const res = await client.fetch("/api/v1/mcp-servers/{id}/tools/review/approve-all/", {
        method: "post",
        params: { path: { id: mcp_server_id } }
      });
      return res;
    },

    /**
     * List MCP servers private to a space (does not include tenant-wide entries).
     * Space members with READ permission on mcp_servers can call this.
     * @param {Object} params
     * @param {string} params.space_id Space ID to list servers for
     * @throws {IntricError}
     * */
    listForSpace: async ({ space_id }) => {
      const res = await client.fetch("/api/v1/spaces/{id}/mcp-servers/", {
        method: "get",
        params: {
          path: { id: space_id }
        }
      });
      return res;
    },

    /**
     * Create a space-private MCP server. Connection is validated before save;
     * the response includes connection details and the discovered tools.
     * @param {Object} params
     * @param {string} params.space_id Space ID to attach the server to
     * @param {string} params.name Name of the MCP server
     * @param {string} params.http_url HTTP URL to the MCP server
     * @param {"none" | "bearer"} [params.http_auth_type] Authentication type (default: none)
     * @param {string} [params.description] Description
     * @param {{[key: string]: unknown} | null} [params.http_auth_config_schema] Auth config
     * @param {string[]} [params.tags] Tags
     * @param {string} [params.icon_url] Icon URL
     * @param {string} [params.documentation_url] Documentation URL
     * @throws {IntricError}
     * */
    createForSpace: async ({
      space_id,
      name,
      http_url,
      http_auth_type,
      description,
      http_auth_config_schema,
      tags,
      icon_url,
      documentation_url
    }) => {
      /** @type {any} */
      const body = {
        name,
        http_url,
        http_auth_type,
        description,
        http_auth_config_schema,
        tags,
        icon_url,
        documentation_url
      };
      const res = await client.fetch("/api/v1/spaces/{id}/mcp-servers/", {
        method: "post",
        params: { path: { id: space_id } },
        requestBody: { "application/json": body }
      });
      return res;
    },

    /**
     * Provision an eneo-knowledge collection and its paired MCP server in one
     * call. The user only supplies a display name; eneo derives the upstream
     * slug and uses the configured default embedding model. The resulting MCP
     * server then appears in the assistant editor like any other.
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @param {string} params.name Display name for the knowledge source
     * @throws {IntricError}
     * */
    createKnowledgeSource: async ({ space_id, name }) => {
      const res = await client.fetch("/api/v1/spaces/{id}/knowledge-sources/", {
        method: "post",
        params: { path: { id: space_id } },
        requestBody: { "application/json": { name } }
      });
      return res;
    },

    /**
     * List knowledge-source ownership rows for a space (sparse: id, slug, mcp_server_id).
     * Used to map MCP server entries to their file-management surface.
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @throws {IntricError}
     * */
    listSpaceKnowledgeSources: async ({ space_id }) => {
      const res = await client.fetch("/api/v1/spaces/{id}/knowledge-sources/", {
        method: "get",
        params: { path: { id: space_id } }
      });
      return res;
    },

    /**
     * List files in a knowledge source (proxy to eneo-knowledge).
     * Status passes through verbatim: queued -> processing -> ready (or failed).
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @param {string} params.knowledge_source_id Knowledge source ownership row ID
     * @throws {IntricError}
     * */
    listKnowledgeSourceFiles: async ({ space_id, knowledge_source_id }) => {
      const res = await client.fetch(
        "/api/v1/spaces/{id}/knowledge-sources/{knowledge_source_id}/files/",
        {
          method: "get",
          params: { path: { id: space_id, knowledge_source_id } }
        }
      );
      return res;
    },

    /**
     * Upload a file to a knowledge source. Returns the file's initial metadata;
     * poll listKnowledgeSourceFiles to follow ingestion.
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @param {string} params.knowledge_source_id Knowledge source ownership row ID
     * @param {File} params.file Browser File to upload
     * @throws {IntricError}
     * */
    uploadKnowledgeSourceFile: async ({ space_id, knowledge_source_id, file }) => {
      const form = new FormData();
      form.append("file", file);
      const res = await client.fetch(
        "/api/v1/spaces/{id}/knowledge-sources/{knowledge_source_id}/files/",
        {
          method: "post",
          params: { path: { id: space_id, knowledge_source_id } },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          requestBody: { "multipart/form-data": /** @type {any} */ (form) }
        }
      );
      return res;
    },

    /**
     * Delete a file from a knowledge source.
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @param {string} params.knowledge_source_id Knowledge source ownership row ID
     * @param {string} params.file_id Upstream file ID
     * @throws {IntricError}
     * */
    deleteKnowledgeSourceFile: async ({ space_id, knowledge_source_id, file_id }) => {
      await client.fetch(
        "/api/v1/spaces/{id}/knowledge-sources/{knowledge_source_id}/files/{file_id}/",
        {
          method: "delete",
          params: { path: { id: space_id, knowledge_source_id, file_id } }
        }
      );
    },

    /**
     * Re-discover and upsert tool definitions for a space-private MCP.
     * Bypasses the pending/approval queue used by the admin path because
     * the user owns this server.
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @param {string} params.mcp_server_id MCP server ID
     * @throws {IntricError}
     * */
    refreshSpaceMcpServerTools: async ({ space_id, mcp_server_id }) => {
      const res = await client.fetch(
        "/api/v1/spaces/{id}/mcp-servers/{mcp_server_id}/refresh-tools/",
        {
          method: "post",
          params: { path: { id: space_id, mcp_server_id } }
        }
      );
      return res;
    },

    /**
     * Delete a space-private MCP server.
     * @param {Object} params
     * @param {string} params.space_id Owning space ID
     * @param {string} params.id MCP server ID to delete
     * @throws {IntricError}
     * */
    deleteFromSpace: async ({ space_id, id }) => {
      await client.fetch("/api/v1/spaces/{id}/mcp-servers/{mcp_server_id}/", {
        method: "delete",
        params: { path: { id: space_id, mcp_server_id: id } }
      });
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
