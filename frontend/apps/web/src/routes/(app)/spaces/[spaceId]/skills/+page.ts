import { SKILL_CATALOG_PAGE_SIZE } from "$lib/features/skills/skillCatalog";

export const load = async (event) => {
  event.depends("space:skills");
  const { eneo, currentSpace } = await event.parent();
  const skills = await eneo.skills.list({
    spaceId: currentSpace.id,
    limit: SKILL_CATALOG_PAGE_SIZE
  });
  return { skills };
};
