export const load = async (event) => {
  event.depends("space:skills");
  const { eneo, currentSpace } = await event.parent();
  const canReadSkills = currentSpace.skill_permissions?.includes("read") ?? false;
  const [app, skills, skillBindings] = await Promise.all([
    eneo.apps.get({ id: event.params.appId }),
    canReadSkills ? eneo.skills.list({ spaceId: currentSpace.id }) : Promise.resolve([]),
    canReadSkills
      ? eneo.skills.listAppBindings({ spaceId: currentSpace.id, appId: event.params.appId })
      : Promise.resolve([])
  ]);
  return { app, skills, skillBindings };
};
