export const load = async (event) => {
  const { eneo } = await event.parent();
  const { organizationSpaceId } = await event.parent();

  event.depends("crawlruns:list");

  const [website, crawlRuns, infoBlobs] = await Promise.all([
    eneo.websites.get({ id: event.params.id }),
    eneo.websites.crawlRuns.list({ id: event.params.id }),
    eneo.websites.indexedBlobs.list({ id: event.params.id })
  ]);

  const isOrgWebsite = organizationSpaceId != null && website.space_id === organizationSpaceId;

  return {
    crawlRuns: crawlRuns.reverse(),
    infoBlobs,
    website,
    readonly: isOrgWebsite
  };
};
