export const load = async (event) => {
  const selectedAppId = event.params.appId;

  const { intric } = await event.parent();

  return {
    app: await intric.apps.get({ id: selectedAppId }),
    results: intric.apps.runs.list({ app: { id: selectedAppId } })
  };
};
