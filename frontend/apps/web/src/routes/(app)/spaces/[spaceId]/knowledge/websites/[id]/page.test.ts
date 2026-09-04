import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

describe("Website detail loader", () => {
  test("loads only the first bounded page of indexed content", async () => {
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
    const getWebsite = vi.fn().mockResolvedValue(website);
    const listCrawlRuns = vi.fn().mockResolvedValue(crawlRuns);
    const listInfoBlobs = vi.fn().mockResolvedValue(infoBlobPage);
    const event = {
      params: { id: website.id },
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({
        organizationSpaceId: "organization-space-id",
        eneo: {
          websites: {
            get: getWebsite,
            crawlRuns: { list: listCrawlRuns },
            indexedBlobs: { listPage: listInfoBlobs }
          }
        }
      })
    };

    const result = await load(event as never);

    expect(event.parent).toHaveBeenCalledOnce();
    expect(event.depends).toHaveBeenCalledWith("crawlruns:list");
    expect(getWebsite).toHaveBeenCalledWith({ id: website.id });
    expect(listCrawlRuns).toHaveBeenCalledWith({ id: website.id });
    expect(listInfoBlobs).toHaveBeenCalledWith({ id: website.id, limit: 100 });
    expect(result).toEqual({
      website,
      crawlRuns: [{ id: "older" }, { id: "newer" }],
      infoBlobPage,
      readonly: false
    });
  });
});
