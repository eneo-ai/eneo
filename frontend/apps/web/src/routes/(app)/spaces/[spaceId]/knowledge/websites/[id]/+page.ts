import { PAGINATION } from "$lib/core/constants";
import { readContentFilters } from "./websiteContentFilters";

export const load = async (event) => {
  const { eneo, organizationSpaceId } = await event.parent();

  event.depends("crawlruns:list");

  const id = event.params.id;
  // A deep link into a directory or a search renders that selection at once,
  // instead of the whole website first and the selection after a second request.
  const filters = readContentFilters(event.url.searchParams);
  const [website, crawlRunPage, infoBlobPage, contentPage] = await Promise.all([
    eneo.websites.get({ id }),
    eneo.websites.crawlRuns.listPage({ id, limit: PAGINATION.PAGE_SIZE }),
    eneo.websites.indexedBlobs.listPage({ id, limit: PAGINATION.PAGE_SIZE }),
    filters.prefix || filters.q
      ? eneo.websites.indexedBlobs.listPage({
          id,
          limit: PAGINATION.PAGE_SIZE,
          ...(filters.prefix ? { prefix: filters.prefix } : {}),
          ...(filters.q ? { q: filters.q } : {})
        })
      : null
  ]);

  const isOrgWebsite = organizationSpaceId != null && website.space_id === organizationSpaceId;

  return {
    crawlRuns: crawlRunPage.items,
    nextCrawlRunCursor: crawlRunPage.next_cursor ?? null,
    totalCrawlRunCount: crawlRunPage.total_count,
    infoBlobPage,
    initialContent: contentPage ? { ...filters, page: contentPage } : null,
    website,
    readonly: isOrgWebsite
  };
};
