import type { CrawlRun, Eneo, Website } from "@eneo/eneo-js";

type WebsiteDetailPoll = {
  crawlRuns: CrawlRun[];
  latestRun: CrawlRun | null;
};

export function mergeLatestCrawlRun(currentRuns: CrawlRun[], latestRun: CrawlRun): CrawlRun[] {
  return [latestRun, ...currentRuns.filter((run) => run.id !== latestRun.id)];
}

export async function pollWebsiteDetail(
  eneo: Eneo,
  website: Website,
  currentRuns: CrawlRun[]
): Promise<WebsiteDetailPoll> {
  const latestRun = await eneo.websites.crawlRuns.latest(website);
  if (!latestRun) return { crawlRuns: currentRuns, latestRun: null };

  // Publish confirmed status before attempting secondary history/content reads.
  return { crawlRuns: mergeLatestCrawlRun(currentRuns, latestRun), latestRun };
}
