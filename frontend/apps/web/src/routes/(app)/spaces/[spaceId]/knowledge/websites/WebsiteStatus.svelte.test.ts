import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import type { WebsiteSparse } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import WebsiteStatus from "./WebsiteStatus.svelte";

function website(latestCrawl: Partial<NonNullable<WebsiteSparse["latest_crawl"]>>): WebsiteSparse {
  return {
    id: "w1",
    url: "https://example.org",
    latest_crawl: {
      status: "complete",
      created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
      finished_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
      pages_failed: 0,
      files_failed: 0,
      ...latestCrawl
    }
  } as unknown as WebsiteSparse;
}

describe("WebsiteStatus", () => {
  it("renders a completed crawl with its relative sync time", async () => {
    render(WebsiteStatus, { website: website({}) });
    await expect
      .element(page.getByText(m.synced_ago({ timeAgo: "" }).trim(), { exact: false }))
      .toBeVisible();
  });

  it("renders a completed crawl with failures", async () => {
    render(WebsiteStatus, { website: website({ pages_failed: 2 }) });
    await expect.element(page.getByText(m.synced_with_warnings())).toBeVisible();
  });
});
