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

export function pruneUnknownMcpServerIds(
  selectedIds: Iterable<string>,
  knownIds: Iterable<string>
): string[] {
  const known = new Set(knownIds);
  return [...selectedIds].filter((id) => known.has(id));
}
