/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric, currentSpace } = await event.parent();

  const [models, security] = await Promise.all([
    intric.models.list({ space: currentSpace }),
    intric.securityClassifications.list()
  ]);

  return {
    models,
    classifications: security.security_classifications,
    isSecurityEnabled: security.security_enabled
  };
};