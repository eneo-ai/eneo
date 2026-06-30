export const load = async (event) => {
  const { eneo } = await event.parent();

  const dashboard = await eneo.dashboard.list();

  return {
    spaces: dashboard.spaces.items.map((space) => space)
  };
};
