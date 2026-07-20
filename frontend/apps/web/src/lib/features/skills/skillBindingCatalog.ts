import type { Eneo } from "@eneo/eneo-js";
import { mergeSkillCatalog, type SkillBindingCandidate } from "$lib/features/skills/skillBindings";

const CATALOGUE_PAGE_LIMIT = 100;

export async function loadSkillBindingCatalog({
  eneo,
  spaceId,
  organizationSpace
}: {
  eneo: Eneo;
  spaceId: string;
  organizationSpace: boolean;
}): Promise<SkillBindingCandidate[]> {
  const [localSkills, catalogue] = await Promise.all([
    organizationSpace ? Promise.resolve([]) : eneo.skills.list({ spaceId }),
    eneo.skills.catalogue.list({ limit: CATALOGUE_PAGE_LIMIT })
  ]);
  return mergeSkillCatalog(localSkills, catalogue.items);
}

export async function searchSkillBindingCatalog(
  eneo: Eneo,
  query: string
): Promise<SkillBindingCandidate[]> {
  const page = await eneo.skills.catalogue.list({
    limit: CATALOGUE_PAGE_LIMIT,
    search: query || undefined
  });
  return page.items;
}
