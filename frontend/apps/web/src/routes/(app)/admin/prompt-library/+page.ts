/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:prompt-library");
  const { eneo } = await event.parent();
  const entries = await eneo.promptLibrary.list();
  return { entries };
};
