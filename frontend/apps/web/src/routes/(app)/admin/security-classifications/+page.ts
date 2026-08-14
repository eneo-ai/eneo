export const load = async (event) => {
  const { eneo } = await event.parent();

  const securityClassifications = await eneo.securityClassifications.list();

  return {
    securityClassifications
  };
};
