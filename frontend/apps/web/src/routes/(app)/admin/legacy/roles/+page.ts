/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:roles:load");

  const { intric } = await event.parent();
  const [roles, permissions] = await Promise.all([
    intric.roles.list(),
    intric.roles.listPermissions()
  ]);

  return {
    customRoles: roles.roles,
    defaultRoles: roles.predefined_roles,
    permissions: permissions.filter((permission) => permission.name !== "flows")
  };
};
