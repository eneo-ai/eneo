import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type McpServer = Schema<"MCPServerSettingsPublic">;
export type McpServerTool = Schema<"MCPServerToolPublic">;
export type McpAuthType = "none" | "bearer";
export type McpServerCreatePayload = Schema<"MCPServerCreate">;
export type McpServerUpdatePayload = Schema<"MCPServerUpdate">;
export type McpServerCreateResponse = Schema<"MCPServerCreateResponse">;

export const MCP_KEY = ["admin-mcp-servers"];
export const mcpToolsKey = (serverId: string) => ["admin-mcp-servers", serverId, "tools"];
export const BUNDLED_KEY = ["admin-mcp-servers", "bundled"];

/**
 * The servers the bundled tool runtime offers this tenant, each with whether
 * it was added, and the runtime's state. A backend without the runtime
 * endpoint offers none.
 */
export function bundledToolsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: BUNDLED_KEY,
    queryFn: async (): Promise<Schema<"BundledToolList">> => {
      const { data, response } = await api.GET("/api/v1/mcp-servers/bundled/");
      if (response.status === 404 || !data) return { items: [], count: 0, runtime: null };
      return data;
    }
  });
}

/**
 * Adds a server of the bundled tool runtime to the tenant. A capability
 * provider is switched in as the tenant default when `activate` is set; a
 * general server is enabled per space afterwards, like any other.
 */
export function createBundledMcpServer(api: EneoClient, tool: string, activate: boolean) {
  return unwrap(
    api.POST("/api/v1/mcp-servers/bundled/{tool}/", {
      params: { path: { tool } },
      body: { activate }
    })
  );
}

export function mcpServersQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: MCP_KEY,
    queryFn: async (): Promise<McpServer[]> => {
      const page = await unwrap(api.GET("/api/v1/mcp-servers/settings/"));
      return page.items;
    }
  });
}

export function mcpServerToolsQueryOptions(api: EneoClient, serverId: string) {
  return queryOptions({
    queryKey: mcpToolsKey(serverId),
    queryFn: async (): Promise<McpServerTool[]> =>
      (
        await unwrap(
          api.GET("/api/v1/mcp-servers/{id}/tools/", { params: { path: { id: serverId } } })
        )
      ).items
  });
}

export type McpServerFlowUsage = Schema<"PublishedToolUsagePublic">;

/**
 * The published flows whose steps call the server's tools. Behind the
 * tenant's flows gate: ask only when the tenant has flows.
 */
export function mcpServerFlowUsageQueryOptions(api: EneoClient, serverId: string) {
  return queryOptions({
    queryKey: ["admin-mcp-servers", serverId, "flow-usage"],
    queryFn: (): Promise<McpServerFlowUsage> =>
      unwrap(
        api.GET("/api/v1/mcp-servers/{mcp_server_id}/flow-usage", {
          params: { path: { mcp_server_id: serverId } }
        })
      )
  });
}

/**
 * Create a global MCP server. The backend validates the connection and returns
 * a 400 on failure, so the resolved response always carries a successful
 * `connection` with the discovered tool count.
 */
export function createMcpServer(
  api: EneoClient,
  body: McpServerCreatePayload
): Promise<McpServerCreateResponse> {
  return unwrap(api.POST("/api/v1/mcp-servers/", { body }));
}

/** Update a global MCP server (partial). Omitted keys are left unchanged. */
export function updateMcpServer(api: EneoClient, id: string, body: McpServerUpdatePayload) {
  return unwrap(api.POST("/api/v1/mcp-servers/{id}/", { params: { path: { id } }, body }));
}

/** Capability activation replaces the tenant's active source for the same purpose. */
export function setCapabilityProviderActive(api: EneoClient, id: string, active: boolean) {
  return active
    ? unwrap(api.POST("/api/v1/mcp-servers/{id}/activate/", { params: { path: { id } } }))
    : unwrap(api.POST("/api/v1/mcp-servers/{id}/deactivate/", { params: { path: { id } } }));
}

/** Toggle tenant-wide enablement: enable creates settings, disable removes them. */
export function setMcpOrgEnabled(api: EneoClient, serverId: string, enabled: boolean) {
  return enabled
    ? unwrap(
        api.POST("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
          params: { path: { mcp_server_id: serverId } },
          body: {}
        })
      )
    : unwrap(
        api.DELETE("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
          params: { path: { mcp_server_id: serverId } }
        })
      );
}

/** Dispatch activation to the contract owned by this server's purpose. */
export function setServerActivation(api: EneoClient, server: McpServer, active: boolean) {
  return server.purpose && server.purpose !== "general"
    ? setCapabilityProviderActive(api, server.id, active)
    : setMcpOrgEnabled(api, server.id, active);
}

/** Delete a global MCP server from the catalog. */
export function deleteMcpServer(api: EneoClient, id: string) {
  return unwrap(api.DELETE("/api/v1/mcp-servers/{id}/", { params: { path: { id } } }));
}

/** Re-fetch the server's tool catalog from the remote MCP server. */
export function syncMcpServerTools(api: EneoClient, serverId: string) {
  return unwrap(
    api.POST("/api/v1/mcp-servers/{id}/tools/sync/", { params: { path: { id: serverId } } })
  );
}

/** Set tenant-level enablement for a single tool. */
export function updateTenantToolEnabled(api: EneoClient, toolId: string, isEnabled: boolean) {
  return unwrap(
    api.PUT("/api/v1/mcp-servers/settings/tools/{tool_id}/", {
      params: { path: { tool_id: toolId } },
      body: { is_enabled: isEnabled }
    })
  );
}

/** Approve pending tool changes (new/changed become active, removed are deleted). */
export function approveToolChanges(api: EneoClient, serverId: string, toolIds: string[]) {
  return unwrap(
    api.POST("/api/v1/mcp-servers/{id}/tools/review/approve/", {
      params: { path: { id: serverId } },
      body: { tool_ids: toolIds }
    })
  );
}

/** Reject pending tool changes (new deleted, changed/removed reverted to active). */
export function rejectToolChanges(api: EneoClient, serverId: string, toolIds: string[]) {
  return unwrap(
    api.POST("/api/v1/mcp-servers/{id}/tools/review/reject/", {
      params: { path: { id: serverId } },
      body: { tool_ids: toolIds }
    })
  );
}

/** Approve all pending tool changes for a server. */
export function approveAllToolChanges(api: EneoClient, serverId: string) {
  return unwrap(
    api.POST("/api/v1/mcp-servers/{id}/tools/review/approve-all/", {
      params: { path: { id: serverId } }
    })
  );
}
