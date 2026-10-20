export type SpaceMcpServerSelectable = {
  id: string;
  is_available: boolean;
  /** A capability provider carries its purpose; a general server has "general" or none. */
  purpose?: string | null;
};

/**
 * The servers a space picks by id: general ones that are available, plus
 * any already saved. A function's provider (web search, image generation,
 * …) is never among them: functions are switched on through the space's
 * enabled_capabilities, and the backend refuses a provider id here.
 */
export function visibleSpaceMcpServers<Server extends SpaceMcpServerSelectable>(
  servers: Server[],
  savedIds: Iterable<string>
): Server[] {
  const selected = new Set(savedIds);
  return servers.filter(
    (server) =>
      (server.purpose == null || server.purpose === "general") &&
      (server.is_available || selected.has(server.id))
  );
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
