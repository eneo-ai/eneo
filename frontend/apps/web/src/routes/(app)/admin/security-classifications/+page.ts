export const load = async (event) => {
  const { eneo } = await event.parent();

  const [securityClassifications, models] = await Promise.all([
    eneo.securityClassifications.list(),
    eneo.models.list()
  ]);

  return {
    securityClassifications,
    models
  };
};
