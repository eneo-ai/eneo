export const load = async (event) => {
  const { eneo } = await event.parent();
  const app = await eneo.apps.get({ id: event.params.appId });
  return { app };
};
