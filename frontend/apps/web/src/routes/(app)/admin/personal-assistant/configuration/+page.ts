/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { loadSkillBindingCatalogPage } from "$lib/features/skills/skillBindingCatalog";

export const load = async (event) => {
  event.depends("admin:governance-policy");
  event.depends("admin:prompt-library");
  event.depends("organization:skills");
  const { eneo } = await event.parent();
  const organizationSpacePromise = eneo.spaces.getOrganizationSpace();
  const skillsPromise = organizationSpacePromise.then((space) =>
    loadSkillBindingCatalogPage({
      eneo,
      spaceId: space.id,
      organizationSpace: true
    })
  );
  const [policy, models, mcpSettings, promptLibrary, modelProviders, organizationSpace, skills] =
    await Promise.all([
      eneo.governancePolicy.get(),
      eneo.models.list(),
      eneo.mcpServers.listSettings(),
      eneo.promptLibrary.list(),
      eneo.modelProviders.list(),
      organizationSpacePromise,
      skillsPromise
    ]);
  return {
    policy,
    models,
    mcpSettings,
    promptLibrary,
    modelProviders,
    organizationSpace,
    skills
  };
};
