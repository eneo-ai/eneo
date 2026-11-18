import type {
  McpServer as AssistantMcpServer,
  McpTool as AssistantMcpTool
} from "@/lib/api/mcp-selection";

export type {
  McpServer as AssistantMcpServer,
  McpTool as AssistantMcpTool,
  McpServerApi as AssistantMcpServerApi
} from "@/lib/api/mcp-selection";
export { mcpServersFromApi as assistantMcpServersFromApi } from "@/lib/api/mcp-selection";

export type AssistantMcpToolSetting = {
  tool_id: string;
  is_enabled: boolean;
};

export function mcpToolDefaultEnabled(tool: AssistantMcpTool): boolean {
  return tool.is_enabled ?? tool.is_enabled_by_default ?? false;
}

/**
 * The servers the picker lists: those offered, with only the tools the space
 * enabled (the assistant never gets the others), then any server an
 * administrator deactivated that the assistant still has. That one has left
 * the offer, but is listed as unavailable so it can be seen and switched off.
 */
export function availableAssistantMcpServers<Server extends AssistantMcpServer>(
  offered: Server[],
  attached: Server[] = []
): Server[] {
  const offeredIds = new Set(offered.map((server) => server.id));
  return [
    ...offered.map((server) => ({
      ...server,
      tools: (server.tools ?? []).filter(
        (tool) => tool.is_enabled !== false && !tool.removed_from_remote
      )
    })),
    ...attached.filter((server) => server.is_enabled === false && !offeredIds.has(server.id))
  ];
}

export function isMcpToolEnabled(
  server: AssistantMcpServer,
  toolId: string,
  settings: AssistantMcpToolSetting[]
): boolean {
  const override = settings.find((setting) => setting.tool_id === toolId);
  if (override) return override.is_enabled;
  const tool = server.tools?.find((candidate) => candidate.id === toolId);
  return tool ? mcpToolDefaultEnabled(tool) : false;
}

function serverToolSettings(
  server: AssistantMcpServer,
  isEnabled: boolean
): AssistantMcpToolSetting[] {
  return (server.tools ?? []).map((tool) => ({ tool_id: tool.id, is_enabled: isEnabled }));
}

/** Switches `server` on or off; `servers` are the servers the picker lists. */
export function toggleMcpServerSelection(
  selectedIds: Set<string>,
  settings: AssistantMcpToolSetting[],
  server: AssistantMcpServer,
  servers: AssistantMcpServer[]
): { selectedIds: Set<string>; settings: AssistantMcpToolSetting[] } {
  const nextIds = new Set(selectedIds);

  if (nextIds.has(server.id)) {
    nextIds.delete(server.id);
    // Only overrides for tools of the servers still selected remain (the
    // backend refuses others): a listed server leaves out the tools the space
    // disabled, so their saved overrides cannot be matched to it.
    const keptToolIds = new Set(
      selectedMcpServers(servers, nextIds).flatMap((kept) =>
        (kept.tools ?? []).map((tool) => tool.id)
      )
    );
    return {
      selectedIds: nextIds,
      settings: settings.filter((setting) => keptToolIds.has(setting.tool_id))
    };
  }

  nextIds.add(server.id);
  const existingToolIds = new Set(settings.map((setting) => setting.tool_id));
  const newSettings = serverToolSettings(server, true).filter(
    (setting) => !existingToolIds.has(setting.tool_id)
  );
  return { selectedIds: nextIds, settings: [...settings, ...newSettings] };
}

export function ensureSelectedMcpToolsTracked(
  selectedServers: AssistantMcpServer[],
  settings: AssistantMcpToolSetting[]
): AssistantMcpToolSetting[] {
  const tracked = new Set(settings.map((setting) => setting.tool_id));
  const missing = selectedServers.flatMap((server) =>
    (server.tools ?? [])
      .filter((tool) => !tracked.has(tool.id))
      .map((tool) => ({ tool_id: tool.id, is_enabled: mcpToolDefaultEnabled(tool) }))
  );
  return missing.length === 0 ? settings : [...settings, ...missing];
}

export function setMcpServerToolsEnabled(
  selectedServers: AssistantMcpServer[],
  settings: AssistantMcpToolSetting[],
  server: AssistantMcpServer,
  isEnabled: boolean
): AssistantMcpToolSetting[] {
  const tracked = ensureSelectedMcpToolsTracked(selectedServers, settings);
  const serverToolIds = new Set((server.tools ?? []).map((tool) => tool.id));
  return tracked.map((setting) =>
    serverToolIds.has(setting.tool_id) ? { ...setting, is_enabled: isEnabled } : setting
  );
}

export function toggleMcpToolSelection(
  selectedServers: AssistantMcpServer[],
  settings: AssistantMcpToolSetting[],
  toolId: string
): AssistantMcpToolSetting[] {
  const tracked = ensureSelectedMcpToolsTracked(selectedServers, settings);
  return tracked.map((setting) =>
    setting.tool_id === toolId ? { ...setting, is_enabled: !setting.is_enabled } : setting
  );
}

export function selectedMcpServers(
  servers: AssistantMcpServer[],
  selectedIds: Set<string>
): AssistantMcpServer[] {
  return servers.filter((server) => selectedIds.has(server.id));
}

export function enabledMcpToolCount(
  server: AssistantMcpServer,
  settings: AssistantMcpToolSetting[]
): number {
  return (server.tools ?? []).filter((tool) => isMcpToolEnabled(server, tool.id, settings)).length;
}
