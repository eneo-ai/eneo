export const load = async (event) => {
  const { intric } = await event.parent();

  return {
    crawlerSettings: await intric.settings.getCrawler()
  };
};
