export const load = async (event) => {
  const { intric, currentSpace } = await event.parent();

  // If no current space (e.g., loading error), fallback to listing all integrations
  if (!currentSpace || !currentSpace.id) {
    const availableIntegrations = await intric.integrations.user.list();
    return { availableIntegrations };
  }

  // Get integrations filtered by space type and auth type
  // Personal spaces: only user OAuth integrations
  // Shared/Org spaces: only tenant app integrations
  const availableIntegrations = await intric.integrations.user.listForSpace(currentSpace);

  return { availableIntegrations };
};
