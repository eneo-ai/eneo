/*
    Copyright (c) 2024 Sundsvalls Kommun
*/

export const load = async (event) => {
  event.depends("admin:user-groups:load");

  const { eneo } = await event.parent();
  const userGroups = await eneo.userGroups.list();

  return {
    userGroups
  };
};
