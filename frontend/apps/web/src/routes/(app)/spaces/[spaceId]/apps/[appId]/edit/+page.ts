import { requireUuidRouteParam } from "$lib/core/routeParams";

export const load = async (event) => {
  const { eneo } = await event.parent();
  const appId = requireUuidRouteParam(event.params.appId, "App");
  const app = await eneo.apps.get({ id: appId });
  return { app };
};
