/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric, settings } = await event.parent();

  event.depends("admin:models:load");
  event.depends("admin:model-providers:load");

  // Fetch credentials only if tenant credentials feature is enabled
  const tenantCredentialsEnabled = settings.tenant_credentials_enabled || false;

  const [securityClassifications, models, providers, favoritesResponse] = await Promise.all([
    intric.securityClassifications.list(),
    intric.models.list(),
    intric.modelProviders.list(),
    intric.modelProviders.getFavorites()
  ]);

  const credentialsResponse = tenantCredentialsEnabled
    ? await intric.credentials.list()
    : undefined;

  return {
    securityClassifications,
    models,
    providers: providers || [],
    favoriteProviders: favoritesResponse?.providers || [],
    credentials: credentialsResponse?.credentials || undefined,
    tenantCredentialsEnabled
  };
};
