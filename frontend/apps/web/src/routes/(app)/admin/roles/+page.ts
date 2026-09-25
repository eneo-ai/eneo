export const load = async (event) => {
  event.depends("admin:roles:load");

  const { eneo } = await event.parent();
  const [roles, permissions, templates] = await Promise.all([
    eneo.roles.list(),
    eneo.roles.listPermissions(),
    eneo.roles.listTemplates()
  ]);

  return { roles: [...roles.roles, ...roles.predefined_roles], permissions, templates };
};
