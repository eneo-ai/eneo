export const load = async (event) => {
  const { intric } = await event.parent();

  const securityClassifications = await intric.securityClassifications.list();

  return {
    securityClassifications
  };
};
