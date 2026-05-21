/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric } = await event.parent();
  const entry = await intric.promptLibrary.get({ id: event.params.id });
  return { entry };
};
