/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { Space } from "@intric/intric-js";

export const load = async (event) => {
  // Register dependency for targeted invalidation when space data changes
  event.depends('spaces:data');

  const { intric, currentSpace: personalSpace, loadedAt } = await event.parent();

  const spaceId = event.params.spaceId;

  // We want to prevent reloading the personal space (and creating a waterfall)
  // if it was already loaded by the parent layout function within a reasonable time delte (aka below 1500ms).
  const loadDelta = new Date().getTime() - new Date(loadedAt).getTime();

  let currentSpace: Space;

  if (!spaceId || spaceId === "personal") {
    currentSpace = loadDelta < 1500 ? personalSpace : await intric.spaces.getPersonalSpace();
  } else {
    currentSpace = await intric.spaces.get({ id: spaceId });
  }

  return {
    currentSpace
  };
};
