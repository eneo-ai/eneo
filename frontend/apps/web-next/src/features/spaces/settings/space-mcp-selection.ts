import { mcpServersFromApi, type McpServer, type McpServerApi } from "@/lib/api/mcp-selection";
import type { Schema } from "@/lib/api/models";

export type SpaceMcpServerSelectable = {
  id: string;
  is_available: boolean;
};

export function visibleSpaceMcpServers<Server extends SpaceMcpServerSelectable>(
  servers: Server[],
  savedIds: Iterable<string>
): Server[] {
  const selected = new Set(savedIds);
  return servers.filter((server) => server.is_available || selected.has(server.id));
}

export function selectedVisibleMcpServerCount(
  servers: SpaceMcpServerSelectable[],
  selectedIds: Iterable<string>
): number {
  const selected = new Set(selectedIds);
  return servers.filter((server) => selected.has(server.id)).length;
}

export type SpaceMcpSelection = {
  serverIds: string[];
  tools: Schema<"MCPToolSetting">[];
};

export type SpaceMcpServerChoice = McpServer &
  Pick<
    Schema<"MCPServerSettingsPublic">,
    "tags" | "is_available" | "readiness_reason" | "security_classification"
  > & {
    tools: NonNullable<McpServer["tools"]>;
    needsTools: boolean;
  };

export function spaceMcpServerChoices(
  catalog: Schema<"MCPServerSettingsPublic">[],
  saved: Schema<"MCPServerPublicDict">[]
): SpaceMcpServerChoice[] {
  const savedById = new Map(mcpServersFromApi(saved).map((server) => [server.id, server]));
  const choices: SpaceMcpServerChoice[] = catalog
    .filter((server) => !server.purpose || server.purpose === "general")
    .map((server) => ({
      ...server,
      tools: [
        ...new Map(
          [...(savedById.get(server.id)?.tools ?? []), ...(server.tools ?? [])].map((tool) => [
            tool.id,
            tool
          ])
        ).values()
      ],
      needsTools: (server.tools?.length ?? 0) < server.tools_count
    }));
  const known = new Set(catalog.map((server) => server.id));
  for (const server of saved) {
    if (known.has(server.id) || (server.purpose && server.purpose !== "general")) continue;
    choices.push({
      ...server,
      security_classification: null,
      tools: savedById.get(server.id)?.tools ?? [],
      is_available: false,
      needsTools: false
    });
  }
  return visibleSpaceMcpServers(choices, savedById.keys());
}

export function spaceMcpSelection(servers: McpServerApi[]): SpaceMcpSelection {
  return {
    serverIds: servers.map((server) => server.id),
    tools: mcpServersFromApi(servers).flatMap((server) =>
      (server.tools ?? []).map((tool) => ({
        tool_id: tool.id,
        is_enabled: tool.is_enabled ?? false
      }))
    )
  };
}

export function setSpaceMcpServer(
  selection: SpaceMcpSelection,
  server: McpServer,
  enabled: boolean
): SpaceMcpSelection {
  const toolIds = new Set((server.tools ?? []).map((tool) => tool.id));
  return {
    serverIds: enabled
      ? [...new Set([...selection.serverIds, server.id])]
      : selection.serverIds.filter((id) => id !== server.id),
    tools: [
      ...selection.tools.filter((setting) => !toolIds.has(setting.tool_id)),
      ...(enabled ? [...toolIds].map((tool_id) => ({ tool_id, is_enabled: true })) : [])
    ]
  };
}

export function setSpaceMcpTool(
  selection: SpaceMcpSelection,
  toolId: string,
  enabled: boolean
): SpaceMcpSelection {
  return {
    ...selection,
    tools: selection.tools.some((setting) => setting.tool_id === toolId)
      ? selection.tools.map((setting) =>
          setting.tool_id === toolId ? { ...setting, is_enabled: enabled } : setting
        )
      : [...selection.tools, { tool_id: toolId, is_enabled: enabled }]
  };
}
