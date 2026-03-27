export const load = async (event) => {
  const selectedAppId = event.params.appId;

  const { eneo } = await event.parent();

  return {
    app: await eneo.apps.get({ id: selectedAppId }),
    results: eneo.apps.runs.list({ app: { id: selectedAppId } })
  };
};
