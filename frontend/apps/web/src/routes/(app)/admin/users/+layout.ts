export const load = async (event) => {
  const { intric } = await event.parent();

  const [roles, userGroups] = await Promise.all([intric.roles.list(), intric.userGroups.list()]);

  return {
    roles: [...roles.roles, ...roles.predefined_roles],
    userGroups
  };
};
