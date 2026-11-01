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

export function availableAssistantMcpServers<Server extends AssistantMcpServer>(
  servers: Server[]
): Server[] {
  return servers.map((server) => ({
    ...server,
    tools: (server.tools ?? []).filter((tool) => !tool.removed_from_remote)
  }));
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

export function toggleMcpServerSelection(
  selectedIds: Set<string>,
  settings: AssistantMcpToolSetting[],
  server: AssistantMcpServer
): { selectedIds: Set<string>; settings: AssistantMcpToolSetting[] } {
  const nextIds = new Set(selectedIds);
  const serverToolIds = new Set((server.tools ?? []).map((tool) => tool.id));

  if (nextIds.has(server.id)) {
    nextIds.delete(server.id);
    return {
      selectedIds: nextIds,
      settings: settings.filter((setting) => !serverToolIds.has(setting.tool_id))
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
