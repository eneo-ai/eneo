/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { ResourcePermission } from "@eneo/eneo-js";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

export const load = async (event) => {
  event.depends("admin:governance-policy");
  event.depends("admin:prompt-library");
  const { eneo } = await event.parent();
  const organizationSpacePromise = eneo.spaces.getOrganizationSpace();
  const skillsPromise = organizationSpacePromise.then((space) =>
    space.skill_permissions.includes(READ_SKILL_PERMISSION)
      ? eneo.skills.list({ spaceId: space.id })
      : []
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
