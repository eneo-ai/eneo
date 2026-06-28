/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { eneo, settings } = await event.parent();

  event.depends("admin:models:load");
  event.depends("admin:model-providers:load");

  // Fetch credentials only if tenant credentials feature is enabled
  const tenantCredentialsEnabled = settings.tenant_credentials_enabled || false;

  const [securityClassifications, models, providers, favoritesResponse] = await Promise.all([
    eneo.securityClassifications.list(),
    eneo.models.list(),
    eneo.modelProviders.list(),
    eneo.modelProviders.getFavorites()
  ]);

  const credentialsResponse = tenantCredentialsEnabled ? await eneo.credentials.list() : undefined;

  return {
    securityClassifications,
    models,
    providers: providers || [],
    favoriteProviders: favoritesResponse?.providers || [],
    credentials: credentialsResponse?.credentials || undefined,
    tenantCredentialsEnabled
  };
};
