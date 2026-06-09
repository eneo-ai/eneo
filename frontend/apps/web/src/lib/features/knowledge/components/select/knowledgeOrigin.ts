/**
 * Helpers for deciding whether a knowledge item belongs to the user's personal space or to a
 * shared/organization space. Items can carry their owning space id in a few different shapes,
 * so {@link ownerSpaceId} probes all of them.
 */

type SpaceOwned = {
  space_id?: string | null;
  spaceId?: string | null;
  space?: { id?: string | null } | null;
  // Items carry a domain-specific metadata bag; we only probe it for a space id.
  metadata?: Record<string, unknown> | null;
};

export function ownerSpaceId(item: SpaceOwned | null | undefined): string | undefined {
  return (
    item?.space_id ??
    item?.spaceId ??
    item?.space?.id ??
    (item?.metadata?.space_id as string | undefined) ??
    (item?.metadata?.spaceId as string | undefined) ??
    undefined
  );
}

/** Personal = no owning space recorded, or owned by the current (personal) space. */
export function isPersonalItem(item: SpaceOwned, currentSpaceId: string | undefined): boolean {
  const sid = ownerSpaceId(item);
  if (!sid) return true;
  return sid === currentSpaceId;
}

/** Org = owned by the configured organization space, or (absent one) any space that isn't current. */
export function isOrgItem(
  item: SpaceOwned,
  currentSpaceId: string | undefined,
  orgSpaceId: string | undefined
): boolean {
  const sid = ownerSpaceId(item);
  if (orgSpaceId) {
    return sid === orgSpaceId;
  }
  if (!currentSpaceId) {
    return false;
  }
  return Boolean(sid) && sid !== currentSpaceId;
}

/**
 * Split a list into personal vs org buckets using the simple rule the picker sections rely on:
 * personal when unowned or owned by the current space, org otherwise.
 */
export function partitionByOrigin<T extends SpaceOwned>(
  items: T[],
  currentSpaceId: string | undefined
): { personal: T[]; org: T[] } {
  const personal: T[] = [];
  const org: T[] = [];
  for (const item of items) {
    const sid = ownerSpaceId(item);
    if (!sid || sid === currentSpaceId) personal.push(item);
    else org.push(item);
  }
  return { personal, org };
}
