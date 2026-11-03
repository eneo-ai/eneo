export type McpTool = {
  id: string;
  name: string;
  title?: string | null;
  description?: string | null;
  is_enabled?: boolean;
  is_enabled_by_default?: boolean;
  removed_from_remote?: boolean;
};

export type McpServer = {
  id: string;
  name: string;
  description?: string | null;
  /** False when an administrator has deactivated the server. */
  is_enabled?: boolean;
  tools?: McpTool[];
};

export type McpServerApi = {
  id: string;
  name: string;
  description?: string | null;
  is_enabled?: boolean;
  tools?: unknown[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function optionalString(value: unknown): string | null | undefined {
  return typeof value === "string" ? value : value === null ? null : undefined;
}

function booleanValue(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function apiTool(value: unknown): McpTool | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.name !== "string") {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    title: optionalString(value.title),
    description: optionalString(value.description),
    is_enabled: booleanValue(value.is_enabled),
    is_enabled_by_default: booleanValue(value.is_enabled_by_default),
    removed_from_remote: booleanValue(value.removed_from_remote)
  };
}

export function mcpServersFromApi(servers: McpServerApi[]): McpServer[] {
  return servers.map((server) => ({
    id: server.id,
    name: server.name,
    description: server.description,
    is_enabled: server.is_enabled,
    tools: (server.tools ?? []).flatMap((tool) => {
      const parsed = apiTool(tool);
      return parsed ? [parsed] : [];
    })
  }));
}
