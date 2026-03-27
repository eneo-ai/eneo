/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:roles:load");

  const { eneo } = await event.parent();
  const [roles, permissions] = await Promise.all([
    eneo.roles.list(),
    eneo.roles.listPermissions()
  ]);

  return { customRoles: roles.roles, defaultRoles: roles.predefined_roles, permissions };
};
