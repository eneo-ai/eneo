import { withSharePointFixtureIntegration } from "$lib/features/integrations/sharepoint/fixtureMode";

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();

  // If no current space (e.g., loading error), fallback to listing all integrations
  if (!currentSpace || !currentSpace.id) {
    const availableIntegrations = await eneo.integrations.user.list();
    return { availableIntegrations };
  }

  // Get integrations filtered by space type and auth type
  // Personal spaces: only user OAuth integrations
  // Shared/Org spaces: only tenant app integrations
  const integrations = await eneo.integrations.user.listForSpace(currentSpace);
  const availableIntegrations = withSharePointFixtureIntegration(
    integrations,
    event.url.searchParams,
    currentSpace.personal ? "user_oauth" : "tenant_app"
  );

  return { availableIntegrations };
};
