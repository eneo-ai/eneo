import { PAGINATION } from "$lib/core/constants";

export const load = async (event) => {
  const { eneo, organizationSpaceId } = await event.parent();

  event.depends("crawlruns:list");

  const [website, crawlRunPage, infoBlobPage] = await Promise.all([
    eneo.websites.get({ id: event.params.id }),
    eneo.websites.crawlRuns.listPage({ id: event.params.id, limit: PAGINATION.PAGE_SIZE }),
    eneo.websites.indexedBlobs.listPage({ id: event.params.id, limit: PAGINATION.PAGE_SIZE })
  ]);

  const isOrgWebsite = organizationSpaceId != null && website.space_id === organizationSpaceId;

  return {
    crawlRuns: crawlRunPage.items,
    nextCrawlRunCursor: crawlRunPage.next_cursor ?? null,
    totalCrawlRunCount: crawlRunPage.total_count,
    infoBlobPage,
    website,
    readonly: isOrgWebsite
  };
};
