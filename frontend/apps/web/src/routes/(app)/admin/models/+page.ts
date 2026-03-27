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

  const promises = [
    eneo.securityClassifications.list(),
    eneo.models.list(),
    eneo.modelProviders.list(),  // Always fetch providers
    eneo.modelProviders.getFavorites()
  ];

  // Add credentials fetch if feature is enabled
  if (tenantCredentialsEnabled) {
    promises.push(eneo.credentials.list());
  }

  const results = await Promise.all(promises);
  let securityClassifications, models, providers, favoritesResponse, credentialsResponse;

  if (tenantCredentialsEnabled) {
    [securityClassifications, models, providers, favoritesResponse, credentialsResponse] = results;
  } else {
    [securityClassifications, models, providers, favoritesResponse] = results;
  }

  return {
    securityClassifications,
    models,
    providers: providers || [],
    favoriteProviders: favoritesResponse?.providers || [],
    credentials: credentialsResponse?.credentials || undefined,
    tenantCredentialsEnabled
  };
};
