import { PAGINATION } from "$lib/core/constants";

export const load = async (event) => {
  const { eneo, organizationSpaceId } = await event.parent();

  event.depends("crawlruns:list");

  const [website, crawlRuns, infoBlobPage] = await Promise.all([
    eneo.websites.get({ id: event.params.id }),
    eneo.websites.crawlRuns.list({ id: event.params.id }),
    eneo.websites.indexedBlobs.listPage({ id: event.params.id, limit: PAGINATION.PAGE_SIZE })
  ]);

  const isOrgWebsite = organizationSpaceId != null && website.space_id === organizationSpaceId;

  return {
    crawlRuns: crawlRuns.reverse(),
    infoBlobPage,
    website,
    readonly: isOrgWebsite
  };
};
