import { requireUuidRouteParam } from "$lib/core/routeParams";

export const load = async (event) => {
  const { eneo } = await event.parent();
  const selectedAppId = requireUuidRouteParam(event.params.appId, "App");
  const selectedRun = requireUuidRouteParam(event.params.resultId, "App run");

  const [app, result] = await Promise.all([
    eneo.apps.get({ id: selectedAppId }),
    eneo.apps.runs.get({ id: selectedRun })
  ]);

  return {
    app,
    result
  };
};
