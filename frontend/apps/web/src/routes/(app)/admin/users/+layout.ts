export const load = async (event) => {
  const { eneo } = await event.parent();

  const [roles, userGroups] = await Promise.all([eneo.roles.list(), eneo.userGroups.list()]);

  return {
    customRoles: roles.roles,
    defaultRoles: roles.predefined_roles,
    userGroups
  };
};
