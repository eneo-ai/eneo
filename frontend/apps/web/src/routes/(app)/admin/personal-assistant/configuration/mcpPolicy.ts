export type McpServerWithTools = {
  id: string;
  tools?: Array<{ id: string }> | null;
};

export function disabledToolIdsForSelectedServers(
  servers: McpServerWithTools[],
  selectedServerIds: Iterable<string>,
  disabledToolIds: Iterable<string>
): string[] {
  const selectedIds = new Set(selectedServerIds);
  const selectableToolIds = new Set(
    servers
      .filter((server) => selectedIds.has(server.id))
      .flatMap((server) => (server.tools ?? []).map((tool) => tool.id))
  );

  return Array.from(disabledToolIds).filter((toolId) => selectableToolIds.has(toolId));
}
