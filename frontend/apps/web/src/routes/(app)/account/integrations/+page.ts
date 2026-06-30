export const load = async (event) => {
  const { eneo } = await event.parent();

  const myIntegrations = await eneo.integrations.user.list();

  return { myIntegrations };
};
