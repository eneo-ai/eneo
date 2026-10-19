/**
 * Knowledge origin is determined by ownership, independently of the user's space membership.
 * The available options and selected sources use the same exhaustive classification, so a
 * source the space can see always has exactly one section and stays removable.
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

export type KnowledgeOrigin = "space" | "organization";

export function classifyKnowledgeOrigin(
  item: SpaceOwned,
  currentSpaceId: string | undefined,
  organizationSpaceId: string | undefined
): KnowledgeOrigin {
  const sid = ownerSpaceId(item);
  // Anything the organization space does not own, including legacy links from another space,
  // belongs to the current space's section.
  if (sid && sid !== currentSpaceId && sid === organizationSpaceId) return "organization";
  return "space";
}

export function partitionByOrigin<T extends SpaceOwned>(
  items: T[],
  currentSpaceId: string | undefined,
  organizationSpaceId: string | undefined
): Record<KnowledgeOrigin, T[]> {
  const partitions: Record<KnowledgeOrigin, T[]> = { space: [], organization: [] };
  for (const item of items) {
    partitions[classifyKnowledgeOrigin(item, currentSpaceId, organizationSpaceId)].push(item);
  }
  return partitions;
}
