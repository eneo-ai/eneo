import { requireUuidRouteParam } from "$lib/core/routeParams";

export const load = async (event) => {
  const selectedAppId = requireUuidRouteParam(event.params.appId, "App");

  const { intric } = await event.parent();

  return {
    app: await intric.apps.get({ id: selectedAppId }),
    results: intric.apps.runs.list({ app: { id: selectedAppId } })
  };
};
