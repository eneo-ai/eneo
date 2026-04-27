import { requireUuidRouteParam } from "$lib/core/routeParams";

export const load = async (event) => {
  const { intric } = await event.parent();
  const appId = requireUuidRouteParam(event.params.appId, "App");
  const app = await intric.apps.get({ id: appId });
  return { app };
};
