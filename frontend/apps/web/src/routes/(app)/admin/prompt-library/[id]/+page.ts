/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:prompt-library");
  const { intric } = await event.parent();
  const entry = await intric.promptLibrary.get({ id: event.params.id });
  const versions = await intric.promptLibrary.versions({ id: event.params.id }).catch((err) => {
    if (err?.status === 404) {
      return { items: [], count: 0 };
    }
    throw err;
  });
  return { entry, versions };
};
