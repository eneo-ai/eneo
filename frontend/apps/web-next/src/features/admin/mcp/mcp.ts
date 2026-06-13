import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type McpServer = Schema<"MCPServerSettingsPublic">;
export type McpAuthType = "none" | "bearer";

export const MCP_KEY = ["admin-mcp-servers"];

export function mcpServersQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: MCP_KEY,
    queryFn: async (): Promise<McpServer[]> => {
      const page = await unwrap(api.GET("/api/v1/mcp-servers/settings/"));
      return page.items;
    }
  });
}
