import {
  emptySkillBindingCatalogPage,
  loadSkillBindingCatalogPage
} from "$lib/features/skills/skillBindingCatalog";

export const load = async (event) => {
  event.depends("space:skills");
  event.depends("organization:skills");
  const { eneo, currentSpace } = await event.parent();
  const canReadSkills = currentSpace.skill_permissions?.includes("read") ?? false;
  const [app, skills, skillBindings] = await Promise.all([
    eneo.apps.get({ id: event.params.appId }),
    canReadSkills
      ? loadSkillBindingCatalogPage({
          eneo,
          spaceId: currentSpace.id,
          organizationSpace: currentSpace.organization === true
        })
      : Promise.resolve(emptySkillBindingCatalogPage()),
    canReadSkills
      ? eneo.skills.listAppBindings({ spaceId: currentSpace.id, appId: event.params.appId })
      : Promise.resolve([])
  ]);
  return { app, skills, skillBindings };
};
