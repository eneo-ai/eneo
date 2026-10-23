import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

const website = { id: "website-id", space_id: "space-id" };
const crawlRuns = [{ id: "newer" }, { id: "older" }];
const infoBlobPage = {
  items: [{ id: "blob-id" }],
  count: 1,
  limit: 100,
  total_count: 1,
  next_cursor: null,
  previous_cursor: null
};

function createEvent(url: string, listInfoBlobs = vi.fn().mockResolvedValue(infoBlobPage)) {
  const getWebsite = vi.fn().mockResolvedValue(website);
  const listCrawlRuns = vi
    .fn()
    .mockResolvedValue({ items: crawlRuns, next_cursor: "older-page", total_count: 120 });
  const event = {
    params: { id: website.id },
    url: new URL(url),
    depends: vi.fn(),
    parent: vi.fn().mockResolvedValue({
      organizationSpaceId: "organization-space-id",
      eneo: {
        websites: {
          get: getWebsite,
          crawlRuns: { listPage: listCrawlRuns },
          indexedBlobs: { listPage: listInfoBlobs }
        }
      }
    })
  };
  return { event, getWebsite, listCrawlRuns, listInfoBlobs };
}

describe("Website detail loader", () => {
  test("loads only the first bounded pages of history and indexed content", async () => {
    const { event, getWebsite, listCrawlRuns, listInfoBlobs } = createEvent(
      "http://localhost/spaces/space/knowledge/websites/website-id"
    );

    const result = await load(event as never);

    expect(event.parent).toHaveBeenCalledOnce();
    expect(event.depends).toHaveBeenCalledWith("crawlruns:list");
    expect(getWebsite).toHaveBeenCalledWith({ id: website.id });
    expect(listCrawlRuns).toHaveBeenCalledWith({ id: website.id, limit: 100 });
    expect(listInfoBlobs).toHaveBeenCalledExactlyOnceWith({ id: website.id, limit: 100 });
    expect(result).toEqual({
      website,
      crawlRuns: [{ id: "newer" }, { id: "older" }],
      nextCrawlRunCursor: "older-page",
      totalCrawlRunCount: 120,
      infoBlobPage,
      initialContent: null,
      readonly: false
    });
  });

  test("a deep link into a directory loads that selection alongside the whole website", async () => {
    const selection = { ...infoBlobPage, items: [{ id: "guide" }] };
    const listInfoBlobs = vi
      .fn()
      .mockImplementation(async ({ prefix }: { prefix?: string }) =>
        prefix ? selection : infoBlobPage
      );
    const prefix = "https://example.test/A/";
    const { event } = createEvent(
      `http://localhost/spaces/space/knowledge/websites/website-id?tab=blobs&prefix=${encodeURIComponent(prefix)}&q=pdf`,
      listInfoBlobs
    );

    const result = await load(event as never);

    expect(listInfoBlobs).toHaveBeenCalledTimes(2);
    expect(listInfoBlobs).toHaveBeenCalledWith({ id: website.id, limit: 100, prefix, q: "pdf" });
    expect(result.infoBlobPage).toBe(infoBlobPage);
    expect(result.initialContent).toEqual({ prefix, q: "pdf", page: selection });
  });

  test("an invalid directory in the link falls back to the whole website", async () => {
    const { event, listInfoBlobs } = createEvent(
      "http://localhost/spaces/space/knowledge/websites/website-id?prefix=docs/"
    );

    const result = await load(event as never);

    expect(listInfoBlobs).toHaveBeenCalledExactlyOnceWith({ id: website.id, limit: 100 });
    expect(result.initialContent).toBeNull();
  });
});
