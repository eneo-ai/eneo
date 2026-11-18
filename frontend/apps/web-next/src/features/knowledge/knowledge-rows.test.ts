import { describe, expect, it } from "vitest";
import { makeWebsite } from "@/features/spaces/testing/space-fixture";
import type { Website } from "./knowledge";
import { websiteRow } from "./knowledge-rows";

describe("websiteRow", () => {
  it("counts the pages the latest run left indexed, unchanged ones too", () => {
    const website = makeWebsite({
      latest_crawl: {
        ...(makeWebsite().latest_crawl as object),
        pages_crawled: 0,
        pages_unchanged: 318
      }
    }) as unknown as Website;
    expect(websiteRow(website, "space-1").content).toEqual({
      key: "space_pages_count",
      values: { count: 318 }
    });
  });

  it("says nothing about pages before the first run", () => {
    const website = makeWebsite({ latest_crawl: null }) as unknown as Website;
    expect(websiteRow(website, "space-1").content).toBeNull();
  });
});
