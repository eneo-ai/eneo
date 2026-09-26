// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeSpace, makeWebsite } from "@/features/spaces/testing/space-fixture";

const state = vi.hoisted(() => ({ runStatus: "complete" as string }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {}, prefetch: () => {} }),
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => makeSpace() as Space) };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const data =
        path === "/api/v1/websites/{id}/"
          ? makeWebsite()
          : path === "/api/v1/websites/{id}/runs/"
            ? {
                items: [
                  {
                    id: "crawl-2",
                    status: state.runStatus,
                    pages_crawled: 12,
                    files_downloaded: 0,
                    pages_failed: 0,
                    files_failed: 0,
                    result_location: null,
                    created_at: "2026-09-25T08:00:00Z",
                    finished_at: null
                  }
                ]
              }
            : path === "/api/v1/websites/{id}/info-blobs/"
              ? { items: [{ id: "blob-1", metadata: { title: "lou.html", size: 2048 } }] }
              : { items: [] };
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { WebsiteDetail } from "./website-detail.client";

afterEach(() => {
  cleanup();
  state.runStatus = "complete";
});

describe("WebsiteDetail", () => {
  it("switches between crawls and indexed content with Astryx tabs", async () => {
    // makeSpace() owns website-1, so the page offers "Synkronisera nu".
    expect(makeSpace().id).toBe(makeWebsite().space_id);
    const { container } = renderInApp(<WebsiteDetail websiteId="website-1" />);

    const tablist = await screen.findByRole("tablist", { name: "Indexeringar och innehåll" });
    const crawls = within(tablist).getByRole("tab", { name: "Indexeringar" });
    expect(crawls.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel", { name: "Indexeringar" })).toBeTruthy();
    // Each tab's table takes the tab's name.
    expect(screen.getByRole("table", { name: "Indexeringar" })).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(within(tablist).getByRole("tab", { name: "Indexerat innehåll" }));
    expect(screen.getByRole("tabpanel", { name: "Indexerat innehåll" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Indexerat innehåll" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("says in text why Synkronisera nu is unavailable while a crawl runs", async () => {
    state.runStatus = "in progress";
    renderInApp(<WebsiteDetail websiteId="website-1" />);

    const sync = await screen.findByRole("button", { name: "Synkronisera nu" });
    expect((sync as HTMLButtonElement).disabled).toBe(true);
    expect(sync.getAttribute("title")).toBeNull();
    const reason = screen.getByText("Kan inte synkronisera medan en crawl redan körs");
    expect(sync.getAttribute("aria-describedby")).toBe(reason.id);
  });

  it("offers Synkronisera nu without a reason when no crawl runs", async () => {
    renderInApp(<WebsiteDetail websiteId="website-1" />);

    const sync = await screen.findByRole("button", { name: "Synkronisera nu" });
    expect((sync as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("Kan inte synkronisera medan en crawl redan körs")).toBeNull();
  });
});
