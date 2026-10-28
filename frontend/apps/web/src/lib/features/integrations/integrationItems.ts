import type { Eneo, IntegrationKnowledge, Space } from "@eneo/eneo-js";

/**
 * The integration items of `space` that match, re-read from the server when none of the
 * loaded ones do. The layout's space is cached until "spaces:data" is invalidated, which
 * an import does not do, so an item imported since only exists on the server.
 */
export async function findIntegrationItems(
  eneo: Pick<Eneo, "spaces">,
  space: Space,
  matches: (item: IntegrationKnowledge) => boolean
): Promise<IntegrationKnowledge[]> {
  const loaded = (space.knowledge.integration_knowledge_list?.items ?? []).filter(matches);
  if (loaded.length > 0) return loaded;
  const fresh = await eneo.spaces.listKnowledge(space);
  return (fresh.integration_knowledge_list?.items ?? []).filter(matches);
}
