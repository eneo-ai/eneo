export const load = async (event) => {
  const { intric } = await event.parent();
  const selectedAppId = event.params.appId;
  const selectedRun = event.params.resultId;

  const [app, result] = await Promise.all([
    intric.apps.get({ id: selectedAppId }),
    intric.apps.runs.get({ id: selectedRun })
  ]);

  return {
    app,
    result
  };
};
