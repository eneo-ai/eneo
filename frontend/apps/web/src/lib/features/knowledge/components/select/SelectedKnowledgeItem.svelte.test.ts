import type { InfoBlob, WebsiteSparse } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const listInfoBlobs = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    websites: { indexedBlobs: { list: listInfoBlobs } }
  })
}));

import SelectedKnowledgeItem from "./SelectedKnowledgeItem.svelte";

function blob(index: number): InfoBlob {
  return {
    id: `00000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    metadata: { title: `Document ${index}` }
  } as InfoBlob;
}

const website = {
  id: crypto.randomUUID(),
  name: "Sundsvall",
  url: "https://sundsvall.se",
  latest_crawl: { pages_crawled: 101, pages_failed: 0 }
} as WebsiteSparse;

describe("SelectedKnowledgeItem", () => {
  beforeEach(() => {
    listInfoBlobs.mockReset();
  });

  it("makes indexed items after the first cursor page reachable", async () => {
    listInfoBlobs
      .mockResolvedValueOnce({
        items: Array.from({ length: 100 }, (_, index) => blob(index + 1)),
        count: 100,
        limit: 100,
        total_count: 101,
        next_cursor: "cursor-100",
        previous_cursor: null
      })
      .mockResolvedValueOnce({
        items: [blob(101)],
        count: 1,
        limit: 100,
        total_count: 101,
        next_cursor: null,
        previous_cursor: null
      });
    render(SelectedKnowledgeItem, {
      kind: "website",
      item: website,
      modelEnabled: true,
      onRemove: vi.fn()
    });

    await page.getByRole("button", { name: m.aria_expand() }).click();
    await expect.element(page.getByText("Document 1", { exact: true })).toBeVisible();

    await page
      .getByRole("button", {
        name: m.website_indexed_content_load_more({ current: 100, total: 101 })
      })
      .click();

    expect(listInfoBlobs).toHaveBeenNthCalledWith(2, {
      id: website.id,
      limit: 100,
      cursor: "cursor-100"
    });
    const next = page.getByRole("button", { name: m.aria_go_to_next_page() });
    for (let pageNumber = 1; pageNumber < 11; pageNumber += 1) {
      await next.click();
    }
    await expect.element(page.getByText("Document 101", { exact: true })).toBeVisible();
  });
});
