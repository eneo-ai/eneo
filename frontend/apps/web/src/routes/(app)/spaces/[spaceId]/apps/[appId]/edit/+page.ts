import { requireUuidRouteParam } from "$lib/core/routeParams";
import {
  canAttachSkills,
  emptySkillBindingCatalogPage,
  loadSkillBindingCatalogPage
} from "$lib/features/skills/skillBindingCatalog";

export const load = async (event) => {
  event.depends("space:skills");
  event.depends("organization:skills");
  const { eneo, currentSpace, user } = await event.parent();
  const appId = requireUuidRouteParam(event.params.appId, "App");
  const canUseSkills = canAttachSkills(currentSpace, user);
  const [app, skills, skillBindings] = await Promise.all([
    eneo.apps.get({ id: appId }),
    canUseSkills
      ? loadSkillBindingCatalogPage({
          eneo,
          spaceId: currentSpace.id,
          organizationSpace: currentSpace.organization === true
        })
      : Promise.resolve(emptySkillBindingCatalogPage()),
    canUseSkills
      ? eneo.skills.listAppBindings({ spaceId: currentSpace.id, appId })
      : Promise.resolve([])
  ]);
  return { app, skills, skillBindings, canUseSkills };
};
