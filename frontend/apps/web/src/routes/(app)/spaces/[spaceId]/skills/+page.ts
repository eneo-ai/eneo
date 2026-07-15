export const load = async (event) => {
  event.depends("space:skills");
  const { eneo, currentSpace } = await event.parent();
  const skills = await eneo.skills.list({ spaceId: currentSpace.id });
  return { skills };
};
