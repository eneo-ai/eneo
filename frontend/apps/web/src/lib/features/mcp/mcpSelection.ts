export type MCPSelectionTool = {
  id?: string;
  name?: string;
  description?: string;
  input_schema?: unknown;
  is_enabled?: boolean;
};

export type MCPSelectionServer = {
  id?: string;
  tools?: MCPSelectionTool[] | null;
  [key: string]: unknown;
};

export type MCPToolSelection = {
  tool_id: string;
  is_enabled: boolean;
};

type SanitizeMcpSelectionInput = {
  selectedServers: MCPSelectionServer[];
  selectedTools: MCPToolSelection[];
  availableServers: MCPSelectionServer[];
};

type SanitizeMcpSelectionResult = {
  selectedServers: MCPSelectionServer[];
  selectedTools: MCPToolSelection[];
};

function toolsById(tools: MCPSelectionTool[] | null | undefined): Map<string, MCPSelectionTool> {
  return new Map(
    (tools ?? [])
      .filter((tool): tool is MCPSelectionTool & { id: string } => typeof tool.id === "string")
      .map((tool) => [tool.id, tool])
  );
}

export function sanitizeMcpSelection(input: SanitizeMcpSelectionInput): SanitizeMcpSelectionResult {
  const availableServersById = new Map(
    input.availableServers
      .filter(
        (server): server is MCPSelectionServer & { id: string } => typeof server.id === "string"
      )
      .map((server) => [server.id, server])
  );
  const selectedToolOverrides = new Map(
    input.selectedTools.map((tool) => [tool.tool_id, tool.is_enabled])
  );

  const selectedServers: MCPSelectionServer[] = [];
  const selectedAvailableToolIds = new Set<string>();

  for (const selectedServer of input.selectedServers) {
    if (typeof selectedServer.id !== "string") continue;

    const availableServer = availableServersById.get(selectedServer.id);
    if (!availableServer) continue;

    const selectedServerTools = toolsById(selectedServer.tools);
    const tools = (availableServer.tools ?? [])
      .filter((tool): tool is MCPSelectionTool & { id: string } => typeof tool.id === "string")
      .map((availableTool) => {
        selectedAvailableToolIds.add(availableTool.id);
        const selectedTool = selectedServerTools.get(availableTool.id);
        const selectedEnabled =
          selectedToolOverrides.get(availableTool.id) ?? selectedTool?.is_enabled ?? false;

        return {
          ...availableTool,
          is_enabled: selectedEnabled
        };
      });

    selectedServers.push({
      ...availableServer,
      tools
    });
  }

  const selectedTools = input.selectedTools.filter((tool) =>
    selectedAvailableToolIds.has(tool.tool_id)
  );

  return {
    selectedServers,
    selectedTools
  };
}
