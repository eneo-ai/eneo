// @vitest-environment jsdom
import { act, cleanup, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import type { IntegrationKnowledge } from "../knowledge";
import { summarizeSource, type QueuedIds, type SourceSummary } from "./sources";
import type { IntegrationSyncProgress, SyncProgressPhase } from "./sync-progress";
import { OUTCOME_WAIT_MS } from "./sync-announcements";
import { useSourceAnnouncements, useSourceListAnnouncements } from "./use-sync-announcements";

const avtal = {
  id: "i1",
  name: "Avtal",
  integration_type: "sharepoint",
  metadata: { size: 0, last_sync_status: "success", document_count: 4 }
} as IntegrationKnowledge;

function running(done: number, phase: SyncProgressPhase = "processing"): IntegrationSyncProgress {
  return {
    integration_knowledge_id: "i1",
    sync_type: "full",
    phase,
    started_at: "2026-10-19T08:00:00Z",
    updated_at: "2026-10-19T08:01:00Z",
    total: 40,
    done,
    indexed: done - 1,
    unchanged: 0,
    skipped: 1,
    deleted: 0
  };
}

const idle = () => summarizeSource([avtal], {});
/** The rows read again after the sync: it is on record now. */
const synced = () =>
  summarizeSource(
    [{ ...avtal, metadata: { ...avtal.metadata!, last_synced_at: "2026-10-19T08:05:00Z" } }],
    {}
  );
const queued = () => summarizeSource([avtal], {}, new Set(["i1"]) as QueuedIds);
const syncing = (done: number, phase?: SyncProgressPhase) =>
  summarizeSource([avtal], { i1: running(done, phase) });

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
  vi.useRealTimers();
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
});

describe("useSourceAnnouncements", () => {
  it("speaks a sync's course, its count at most every 10 s or on a new phase", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2026-10-19T08:00:00Z"));
    const said = recordAnnouncements();
    let summary = idle();
    const { rerender } = renderHookInApp(() => useSourceAnnouncements("Avtal", summary, null));
    const show = async (next: SourceSummary) => {
      summary = next;
      rerender();
      await frame();
    };
    await frame();
    // What the page opens with is not news.
    expect(said).toEqual([]);

    summary = queued();
    rerender();
    await show(syncing(1));
    vi.setSystemTime(Date.parse("2026-10-19T08:00:05Z"));
    await show(syncing(8));
    vi.setSystemTime(Date.parse("2026-10-19T08:00:11Z"));
    await show(syncing(12));
    await show(syncing(40, "finishing"));
    // The progress is gone before the rows say how the sync went: not yet news.
    await show(idle());
    await show(synced());

    // The queued sync started before the region took the first text.
    expect(said).toEqual([
      "Synk av Avtal har startat",
      "Avtal: 12 av 40 lästa",
      "Avtal: 40 av 40 lästa",
      "Synk av Avtal klar"
    ]);
  });

  it("says a sync is no longer running when its rows do not tell how it went in time", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    const said = recordAnnouncements();
    let summary = idle();
    const { rerender } = renderHookInApp(() => useSourceAnnouncements("Avtal", summary, null));
    const show = async (next: SourceSummary) => {
      summary = next;
      rerender();
      await act(async () => {});
    };
    await show(syncing(1));
    await show(idle());
    expect(said).toEqual([]);

    await act(() => vi.advanceTimersByTimeAsync(OUTCOME_WAIT_MS));
    vi.useRealTimers();
    await frame();
    expect(said).toEqual(["Synk av Avtal pågår inte längre"]);
  });

  it("keeps a change notification's sync quiet", async () => {
    const said = recordAnnouncements();
    let summary = idle();
    const { rerender } = renderHookInApp(() => useSourceAnnouncements("Avtal", summary, null));
    await frame();
    for (const next of [
      summarizeSource([avtal], { i1: { ...running(1), sync_type: "delta" } }),
      idle(),
      synced()
    ]) {
      summary = next;
      rerender();
      await frame();
    }
    expect(said).toEqual([]);
  });

  it("speaks a queued sync, and a changed number of problems once the lists are in", async () => {
    const said = recordAnnouncements();
    let summary = idle();
    let problems: number | null = null;
    const { rerender } = renderHookInApp(() => useSourceAnnouncements("Avtal", summary, problems));
    const show = async (next: SourceSummary, count: number | null) => {
      summary = next;
      problems = count;
      rerender();
      await frame();
    };
    await show(idle(), 1);
    expect(said).toEqual([]);

    await show(queued(), 1);
    await show(queued(), 2);
    expect(said).toEqual(["Synk av Avtal köad", "Problem: 2"]);
  });
});

describe("useSourceListAnnouncements", () => {
  it("speaks a sync started from the list being queued, starting and finishing, not its count", async () => {
    const said = recordAnnouncements();
    const row = (summary: SourceSummary) => [{ id: "item-i1", name: "Avtal", summary }];
    let rows = row(idle());
    const { rerender } = renderHookInApp(() => useSourceListAnnouncements(rows));

    for (const summary of [
      queued(),
      syncing(1),
      syncing(30),
      syncing(40, "finishing"),
      idle(),
      synced()
    ]) {
      rows = row(summary);
      rerender();
      await frame();
    }
    // A source that appears (a fresh import) is not news either.
    rows = [...row(idle()), { id: "item-i2", name: "Policy", summary: syncing(1) }];
    rerender();
    await frame();

    await waitFor(() =>
      expect(said).toEqual([
        "Synk av Avtal köad",
        "Synk av Avtal har startat",
        "Synk av Avtal klar"
      ])
    );
  });

  it("leaves a sync it did not see queued to the source's own page", async () => {
    const said = recordAnnouncements();
    const row = (summary: SourceSummary) => [{ id: "item-i1", name: "Avtal", summary }];
    let rows = row(idle());
    const { rerender } = renderHookInApp(() => useSourceListAnnouncements(rows));
    for (const summary of [syncing(1), idle(), synced()]) {
      rows = row(summary);
      rerender();
      await frame();
    }
    expect(said).toEqual([]);
  });
});

it("combines simultaneous source transitions instead of losing all but the last", async () => {
  let summary = idle();
  const { rerender } = renderHookInApp(() =>
    useSourceListAnnouncements([
      { id: "a", name: "Avtal", summary },
      { id: "b", name: "Policy", summary }
    ])
  );
  await frame();
  summary = queued();
  rerender();
  await frame();
  expect(liveRegion()).toBe("Synk av Avtal köad. Synk av Policy köad");
});

it("keeps a source transition and problem change in the same announcement", async () => {
  let summary = idle();
  let problems = 0;
  const { rerender } = renderHookInApp(() => useSourceAnnouncements("Avtal", summary, problems));
  await frame();
  summary = queued();
  problems = 2;
  rerender();
  await frame();
  expect(liveRegion()).toBe("Synk av Avtal köad. Problem: 2");
});
