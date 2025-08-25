/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { LayoutLoad } from "./$types";
import type { Space } from "@intric/intric-js";

export const load: LayoutLoad = async (event) => {
  const { intric, currentSpace: parentSpace, organizationSpace, loadedAt } = await event.parent();
  const spaceId = event.params.spaceId;

  let currentSpace: Space = parentSpace;
  const loadDelta = new Date().getTime() - new Date(loadedAt).getTime();

  if (!spaceId || spaceId === "personal") {
    currentSpace = loadDelta < 1500 ? parentSpace : await intric.spaces.getPersonalSpace();

  } else if (
    spaceId === "organization" || 
    spaceId === organizationSpace?.id
  ) {
    currentSpace =
      loadDelta < 1500 && organizationSpace
        ? organizationSpace
        : await intric.spaces.getOrganizationSpace();
  } else {
    currentSpace = await intric.spaces.get({ id: spaceId });
  }

  return {
    currentSpace,
    organizationSpaceId: organizationSpace?.id ?? null
  };
};
