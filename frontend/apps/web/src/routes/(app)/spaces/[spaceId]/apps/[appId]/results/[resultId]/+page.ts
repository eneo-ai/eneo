import { requireUuidRouteParam } from "$lib/core/routeParams";

export const load = async (event) => {
  const { intric } = await event.parent();
  const selectedAppId = requireUuidRouteParam(event.params.appId, "App");
  const selectedRun = requireUuidRouteParam(event.params.resultId, "App run");

  const [app, result] = await Promise.all([
    intric.apps.get({ id: selectedAppId }),
    intric.apps.runs.get({ id: selectedRun })
  ]);

  return {
    app,
    result
  };
};
