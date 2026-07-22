export const load = async (event) => {
  event.depends("space:skills");
  const { eneo, currentSpace } = await event.parent();
  const [skill, revisionPage] = await Promise.all([
    eneo.skills.get({ spaceId: currentSpace.id, skillId: event.params.skillId }),
    eneo.skills.listRevisionSummaries({
      spaceId: currentSpace.id,
      skillId: event.params.skillId
    })
  ]);
  return { skill, revisionPage };
};
