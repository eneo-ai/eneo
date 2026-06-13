export type McpServerWithTools = {
  id: string;
  tools?: Array<{ id: string }> | null;
};

/**
 * Narrow a deny-set of tool ids to only those belonging to a currently-selected
 * server. Tool overrides for a server that is no longer allowed are meaningless
 * and would inflate the payload, so they are dropped at save time.
 */
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
