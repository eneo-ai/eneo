import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type McpServer = Schema<"MCPServerSettingsPublic">;
export type McpServerTool = Schema<"MCPServerToolPublic">;
export type McpAuthType = "none" | "bearer";

export const MCP_KEY = ["admin-mcp-servers"];
export const mcpToolsKey = (serverId: string) => ["admin-mcp-servers", serverId, "tools"];

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

/** Re-fetch the server's tool catalog from the remote MCP server. */
export function syncMcpServerTools(api: EneoClient, serverId: string) {
  return unwrap(
    api.POST("/api/v1/mcp-servers/{id}/tools/sync/", { params: { path: { id: serverId } } })
  );
}
