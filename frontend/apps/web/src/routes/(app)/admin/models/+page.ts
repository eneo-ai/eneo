/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric, settings } = await event.parent();

  event.depends("admin:models:load");

  // Fetch credentials only if tenant credentials feature is enabled
  const tenantCredentialsEnabled = settings.tenant_credentials_enabled || false;

  const promises = [
    intric.securityClassifications.list(),
    intric.models.list()
  ];

  // Add credentials fetch if feature is enabled
  if (tenantCredentialsEnabled) {
    promises.push(intric.credentials.list());
  }

  const results = await Promise.all(promises);
  const [securityClassifications, models, credentialsResponse] = results;

  return {
    securityClassifications,
    models,
    credentials: credentialsResponse?.credentials || undefined,
    tenantCredentialsEnabled
  };
};
