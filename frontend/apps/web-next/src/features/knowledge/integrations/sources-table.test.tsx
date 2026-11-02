// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import type { IntegrationKnowledge } from "../knowledge";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: vi.fn(), POST: vi.fn() } }));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ trackJob: vi.fn() }) }));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import { SourcesList } from "./sources-table";
import { groupIntegrationSources, type QueuedIds } from "./sources";
import type { IntegrationSyncProgress, ProgressById } from "./sync-progress";

const avtal = {
  id: "i1",
  name: "Avtal",
  integration_type: "sharepoint",
  wrapper_id: null,
  selected_item_type: "file",
  space_id: "space-1",
  embedding_model: { id: "embed-1" },
  permissions: ["read", "edit", "delete"],
  metadata: {
    size: 0,
    last_sync_status: "success",
    last_synced_at: "2026-10-14T08:00:00Z",
    document_count: 4
  }
} as IntegrationKnowledge;
const policy = { ...avtal, id: "i2", name: "Policy" } as IntegrationKnowledge;

function running(done: number): IntegrationSyncProgress {
  return {
    integration_knowledge_id: "i1",
    sync_type: "full",
    phase: "processing",
    started_at: "2026-10-19T08:00:00Z",
    updated_at: "2026-10-19T08:01:00Z",
    total: 12,
    done,
    indexed: done - 1,
    unchanged: 0,
    skipped: 1,
    deleted: 0
  };
}

const NOTHING_QUEUED: QueuedIds = new Set();

function list(
  progress: ProgressById = {},
  queued: QueuedIds = NOTHING_QUEUED,
  items: IntegrationKnowledge[] = [avtal, policy]
) {
  const sources = groupIntegrationSources(items, (a, b) => a.localeCompare(b));
  return (
    <>
      <h2 id="sources">Källor</h2>
      <SourcesList
        groups={[{ key: "all", heading: null, sources }]}
        progress={progress}
        queued={queued}
        progressLoaded
        name={{ "aria-labelledby": "sources" }}
      />
    </>
  );
}

function liveRegion() {
  return document.querySelector("[data-astryx-live-region='polite']")?.textContent ?? "";
}

/** Every text the polite live region is given from now on, in order. */
function recordAnnouncements() {
  const said: string[] = [];
  const observer = new MutationObserver(() => {
    const text = liveRegion();
    if (text && text !== said.at(-1)) said.push(text);
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  return said;
}

/** Lets the live region take the text (it sets it on the next animation frame). */
const frame = () => act(() => new Promise((resolve) => requestAnimationFrame(resolve)));

afterEach(() => {
  cleanup();
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
});

describe("SourcesList", () => {
  it("shows a source whose sync was queued from here as queued, among the syncing ones", async () => {
    const { container } = renderInApp(list({}, new Set(["i1"])));

    const row = screen.getByRole("link", { name: "Avtal" }).closest("tr")!;
    expect(within(row).getByText("Köad")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Synkar 1" })).toBeTruthy();
    await expectNoAxeViolations(container);

    // Its menu offers no second sync; the other source's still does.
    fireEvent.click(within(row).getByRole("button", { name: "Fler åtgärder för Avtal" }));
    const busy = await screen.findByRole("menuitem", {
      name: "En synk är redan köad eller pågår"
    });
    expect(busy.getAttribute("aria-disabled")).toBe("true");
    fireEvent.keyDown(busy, { key: "Escape" });
    const other = screen.getByRole("link", { name: "Policy" }).closest("tr")!;
    fireEvent.click(within(other).getByRole("button", { name: "Fler åtgärder för Policy" }));
    expect(await screen.findByRole("menuitem", { name: "Fullständig synk" })).toBeTruthy();
  });

  it("speaks a sync started here being queued, starting and finishing, but not its count", async () => {
    const said = recordAnnouncements();
    const { rerender } = renderInApp(list());
    await frame();
    expect(said).toEqual([]);

    // Policy's sync was not started from the list: its own page speaks of it.
    const synced = {
      ...avtal,
      metadata: { ...avtal.metadata!, last_synced_at: "2026-10-19T08:05:00Z" }
    } as IntegrationKnowledge;
    for (const [progress, queued, items] of [
      [{}, new Set(["i1"]), undefined],
      [{ i1: running(1), i2: { ...running(1), integration_knowledge_id: "i2" } }, NOTHING_QUEUED],
      [{ i1: running(9) }, NOTHING_QUEUED],
      [{}, NOTHING_QUEUED],
      [{}, NOTHING_QUEUED, [synced, policy]]
    ] as const) {
      rerender(list(progress, queued, items ? [...items] : undefined));
      await frame();
    }

    await waitFor(() =>
      expect(said).toEqual([
        "Synk av Avtal köad",
        "Synk av Avtal har startat",
        "Synk av Avtal klar"
      ])
    );
  });
});
