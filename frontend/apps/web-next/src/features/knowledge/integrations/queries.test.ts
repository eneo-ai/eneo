import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import type { IntegrationKnowledge } from "../knowledge";
import {
  addOlderSyncLogs,
  shownSyncLogWindow,
  skippedDocumentsQueryOptions,
  syncLogWindowQueryOptions,
  type SyncLog,
  type SyncLogWindow
} from "./queries";
import type { SkippedDocuments } from "./source-problems";

const api = {} as EneoClient;

function revision(syncedAt: string): IntegrationKnowledge {
  return {
    id: "i1",
    metadata: { size: 0, last_synced_at: syncedAt, document_count: 1 }
  } as IntegrationKnowledge;
}

const earlier = revision("2026-10-14T08:00:00Z");
const newer = revision("2026-10-15T08:00:00Z");
const next = revision("2026-10-16T08:00:00Z");

const logs = (...ids: string[]) => ids.map((id) => ({ id }) as SyncLog);

/** Caches the newer revision's window first and writes the earlier one's later. */
function cacheTwoRevisions() {
  const queryClient = new QueryClient();
  const newerWindow: SyncLogWindow = { logs: logs("l9", "l8"), total: 9 };
  const earlierWindow: SyncLogWindow = { logs: logs("l8"), total: 8 };
  const key = (item: IntegrationKnowledge) =>
    syncLogWindowQueryOptions(api, queryClient, "space-1", item).queryKey;
  queryClient.setQueryData(key(newer), newerWindow, { updatedAt: 1_000 });
  queryClient.setQueryData(key(earlier), earlierWindow, { updatedAt: 2_000 });
  return { queryClient, key, newerWindow, earlierWindow };
}

describe("the history an item shows while a new revision loads", () => {
  it("is the newest revision's, also when an earlier one was written after it", () => {
    const { queryClient, newerWindow } = cacheTwoRevisions();
    expect(shownSyncLogWindow(queryClient, "space-1", "i1")).toBe(newerWindow);
  });

  it("takes an older page into the newest revision's window", () => {
    const { queryClient, key, earlierWindow } = cacheTwoRevisions();
    addOlderSyncLogs(queryClient, "space-1", "i1", { items: logs("l7"), total_count: 9 }, "l8");
    expect(queryClient.getQueryData<SyncLogWindow>(key(newer))?.logs.map((log) => log.id)).toEqual([
      "l9",
      "l8",
      "l7"
    ]);
    expect(queryClient.getQueryData(key(earlier))).toBe(earlierWindow);
    // So the next revision starts from it.
    expect(shownSyncLogWindow(queryClient, "space-1", next.id)?.logs).toHaveLength(3);
  });

  it("keeps the newest revision's skipped files on screen while the next one loads", () => {
    const queryClient = new QueryClient();
    const skipped = (total: number): SkippedDocuments => ({
      items: [],
      total,
      truncated: false,
      synced_at: null
    });
    const key = (item: IntegrationKnowledge) =>
      skippedDocumentsQueryOptions(api, queryClient, "space-1", item).queryKey;
    queryClient.setQueryData(key(newer), skipped(2), { updatedAt: 1_000 });
    queryClient.setQueryData(key(earlier), skipped(1), { updatedAt: 2_000 });

    const placeholder = skippedDocumentsQueryOptions(api, queryClient, "space-1", next)
      .placeholderData as () => SkippedDocuments | undefined;
    expect(placeholder()?.total).toBe(2);
  });
});

it("does not reuse a source history through a different space's access context", () => {
  const { queryClient } = cacheTwoRevisions();
  expect(shownSyncLogWindow(queryClient, "another-space", "i1")).toBeUndefined();
});
