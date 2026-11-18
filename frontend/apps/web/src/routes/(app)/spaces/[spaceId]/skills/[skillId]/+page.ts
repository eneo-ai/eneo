import { loadPersonalChatSkillConfiguration } from "$lib/features/skills/personalChatSkills";

export const load = async (event) => {
  event.depends("space:skills");
  const { eneo, currentSpace } = await event.parent();
  const [skill, revisionPage, personalChatSkills] = await Promise.all([
    eneo.skills.get({ spaceId: currentSpace.id, skillId: event.params.skillId }),
    eneo.skills.listRevisionSummaries({
      spaceId: currentSpace.id,
      skillId: event.params.skillId
    }),
    loadPersonalChatSkillConfiguration(eneo, currentSpace)
  ]);
  return { skill, revisionPage, personalChatSkills };
};
