/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { LayoutLoad } from "./$types";
import type { Space } from "@intric/intric-js";

export const load: LayoutLoad = async (event) => {
  const { intric, user, currentSpace: parentSpace, organizationSpace, loadedAt } = await event.parent();
  const spaceId = event.params.spaceId;

  let currentSpace: Space = parentSpace;
  const loadDelta = new Date().getTime() - new Date(loadedAt).getTime();

  // Check if user is admin before attempting to fetch org space
  const isAdmin = user?.predefined_roles?.some((role) =>
    role.permissions?.includes('admin')
  );

  if (!spaceId || spaceId === "personal") {
    currentSpace = loadDelta < 1500 ? parentSpace : await intric.spaces.getPersonalSpace();

  } else if (
    spaceId === "organization" ||
    spaceId === organizationSpace?.id
  ) {
    currentSpace =
      loadDelta < 1500 && organizationSpace
        ? organizationSpace
        : isAdmin ? await intric.spaces.getOrganizationSpace() : null;
  } else {
    currentSpace = await intric.spaces.get({ id: spaceId });
  }

  return {
    currentSpace,
    organizationSpaceId: organizationSpace?.id ?? null
  };
};
