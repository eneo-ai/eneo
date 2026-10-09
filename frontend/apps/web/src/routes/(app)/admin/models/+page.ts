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

  const [securityClassifications, models, providers, favoritesResponse, transcriptionServices] =
    await Promise.all([
      eneo.securityClassifications.list(),
      eneo.models.list(),
      eneo.modelProviders.list(),
      eneo.modelProviders.getFavorites(),
      // An organisation connects at most 200 services (the backend's limit,
      // one page), so a single page holds them all. A failure stays in the
      // speaker identification section instead of taking the page down.
      eneo.transcriptionServices
        .list({ limit: 200 })
        .then((page) => page.items)
        .catch(() => null)
    ]);

  const credentialsResponse = tenantCredentialsEnabled ? await eneo.credentials.list() : undefined;

  return {
    securityClassifications,
    models,
    providers: providers || [],
    favoriteProviders: favoritesResponse?.providers || [],
    transcriptionServices,
    credentials: credentialsResponse?.credentials || undefined,
    tenantCredentialsEnabled
  };
};
