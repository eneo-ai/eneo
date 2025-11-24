/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric, settings } = await event.parent();

  event.depends("admin:models:load");
  event.depends("admin:model-providers:load");

  // Debug: log settings to see what we receive
  console.log('Settings received:', settings);

  // Fetch credentials only if tenant credentials feature is enabled
  const tenantCredentialsEnabled = settings.tenant_credentials_enabled || false;
  const tenantModelsEnabled = settings.tenant_models_enabled || false;

  console.log('tenantModelsEnabled:', tenantModelsEnabled);

  const promises = [
    intric.securityClassifications.list(),
    intric.models.list()
  ];

  // Add provider fetch if tenant models feature is enabled
  if (tenantModelsEnabled) {
    promises.push(intric.modelProviders.list());
  }

  // Add credentials fetch if feature is enabled
  if (tenantCredentialsEnabled) {
    promises.push(intric.credentials.list());
  }

  const results = await Promise.all(promises);
  let securityClassifications, models, providers, credentialsResponse;

  if (tenantModelsEnabled && tenantCredentialsEnabled) {
    [securityClassifications, models, providers, credentialsResponse] = results;
  } else if (tenantModelsEnabled) {
    [securityClassifications, models, providers] = results;
  } else if (tenantCredentialsEnabled) {
    [securityClassifications, models, credentialsResponse] = results;
  } else {
    [securityClassifications, models] = results;
  }

  return {
    securityClassifications,
    models,
    providers: providers || [],
    credentials: credentialsResponse?.credentials || undefined,
    tenantCredentialsEnabled,
    tenantModelsEnabled
  };
};
