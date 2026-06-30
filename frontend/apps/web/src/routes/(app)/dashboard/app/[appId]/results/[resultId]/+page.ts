export const load = async (event) => {
  const { eneo } = await event.parent();
  const selectedAppId = event.params.appId;
  const selectedRun = event.params.resultId;

  const [app, result] = await Promise.all([
    eneo.apps.get({ id: selectedAppId }),
    eneo.apps.runs.get({ id: selectedRun })
  ]);

  return {
    app,
    result
  };
};
