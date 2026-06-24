/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:prompt-library");
  const { intric } = await event.parent();
  const entries = await intric.promptLibrary.list();
  return { entries };
};
