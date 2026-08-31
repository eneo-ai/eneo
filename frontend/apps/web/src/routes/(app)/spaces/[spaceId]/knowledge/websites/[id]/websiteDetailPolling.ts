import type { CrawlRun, Eneo, Website, WebsiteInfoBlobPage } from "@eneo/eneo-js";
import { PAGINATION } from "$lib/core/constants";
import { isActiveCrawlRun } from "$lib/features/knowledge/crawlRunState";

type WebsiteDetailPoll = {
  crawlRuns: CrawlRun[];
  infoBlobPage?: WebsiteInfoBlobPage;
};

export async function pollWebsiteDetail(
  eneo: Eneo,
  website: Website,
  currentRuns: CrawlRun[]
): Promise<WebsiteDetailPoll> {
  const hadActiveRun = currentRuns.some(isActiveCrawlRun);
  const crawlRuns = [...(await eneo.websites.crawlRuns.list(website))].reverse();

  if (!hadActiveRun || crawlRuns.some(isActiveCrawlRun)) {
    return { crawlRuns };
  }

  const infoBlobPage = await eneo.websites.indexedBlobs.list({
    id: website.id,
    limit: PAGINATION.PAGE_SIZE
  });
  return { crawlRuns, infoBlobPage };
}
