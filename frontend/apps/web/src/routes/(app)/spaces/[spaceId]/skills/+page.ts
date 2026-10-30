import { SKILL_CATALOG_PAGE_SIZE } from "$lib/features/skills/skillCatalog";
import { loadPersonalChatSkillConfiguration } from "$lib/features/skills/personalChatSkills";

export const load = async (event) => {
  event.depends("space:skills");
  const { eneo, currentSpace } = await event.parent();
  const [skills, personalChatSkills] = await Promise.all([
    eneo.skills.list({
      spaceId: currentSpace.id,
      limit: SKILL_CATALOG_PAGE_SIZE
    }),
    loadPersonalChatSkillConfiguration(eneo, currentSpace)
  ]);
  return { skills, personalChatSkills };
};
