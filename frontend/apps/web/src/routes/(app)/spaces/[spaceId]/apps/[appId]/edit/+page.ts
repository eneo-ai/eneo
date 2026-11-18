import {
  canAttachSkills,
  emptySkillBindingCatalogPage,
  loadSkillBindingCatalogPage
} from "$lib/features/skills/skillBindingCatalog";

export const load = async (event) => {
  event.depends("space:skills");
  event.depends("organization:skills");
  const { eneo, currentSpace, user } = await event.parent();
  const canUseSkills = canAttachSkills(currentSpace, user);
  const [app, skills, skillBindings] = await Promise.all([
    eneo.apps.get({ id: event.params.appId }),
    canUseSkills
      ? loadSkillBindingCatalogPage({
          eneo,
          spaceId: currentSpace.id,
          organizationSpace: currentSpace.organization === true
        })
      : Promise.resolve(emptySkillBindingCatalogPage()),
    canUseSkills
      ? eneo.skills.listAppBindings({ spaceId: currentSpace.id, appId: event.params.appId })
      : Promise.resolve([])
  ]);
  return { app, skills, skillBindings, canUseSkills };
};
