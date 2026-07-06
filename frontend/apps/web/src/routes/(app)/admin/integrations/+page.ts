export const load = async (event) => {
  const { eneo } = await event.parent();

  const tenantIntegrations = await eneo.integrations.tenant.list();

  return { tenantIntegrations };
};
