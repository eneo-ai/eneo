import { requireUuidRouteParam } from "$lib/core/routeParams";

export const load = async (event) => {
  const selectedAppId = requireUuidRouteParam(event.params.appId, "App");

  const { eneo } = await event.parent();

  return {
    app: await eneo.apps.get({ id: selectedAppId }),
    results: eneo.apps.runs.list({ app: { id: selectedAppId } })
  };
};
