/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  event.depends("admin:roles:load");

  const { intric } = await event.parent();
  const [roles, permissions, templates] = await Promise.all([
    intric.roles.list(),
    intric.roles.listPermissions(),
    intric.roles.listTemplates()
  ]);

  return { allRoles: [...roles.roles, ...roles.predefined_roles], permissions, templates };
};
