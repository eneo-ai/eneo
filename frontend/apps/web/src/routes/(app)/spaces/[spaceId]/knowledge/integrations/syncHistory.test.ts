import { describe, expect, it } from "vitest";
import {
  readSyncLogExtras,
  skippedNotListed,
  summarizeSyncLogPage,
  type SyncLog
} from "./syncHistory";

function log(overrides: Partial<SyncLog>): SyncLog {
  return {
    id: "log-1",
    integration_knowledge_id: "k-1",
    sync_type: "delta",
    status: "success",
    started_at: "2026-10-01T10:00:00Z",
    created_at: "2026-10-01T10:00:00Z",
    files_processed: 0,
    files_deleted: 0,
    pages_processed: 0,
    folders_processed: 0,
    skipped_items: 0,
    skipped_details: [],
    duration_seconds: null,
    ...overrides
  } as SyncLog;
}

describe("readSyncLogExtras", () => {
  it("reads the unchanged count, the truncation flag and the reconcile warning", () => {
    expect(
      readSyncLogExtras(
        log({
          metadata: {
            unchanged_items: 7,
            skipped_truncated: true,
            reconcile_warning: "Delta token reset"
          } as SyncLog["metadata"]
        })
      )
    ).toEqual({ unchangedItems: 7, skippedTruncated: true, reconcileWarning: "Delta token reset" });
  });

  it("defaults for syncs recorded before the fields existed", () => {
    expect(readSyncLogExtras(log({ metadata: null }))).toEqual({
      unchangedItems: 0,
      skippedTruncated: false,
      reconcileWarning: null
    });
  });
});

describe("skippedNotListed", () => {
  it("is the skipped count minus the listed details, never negative", () => {
    const details = [{ file: "a", reason: "r" }];
    expect(skippedNotListed(log({ skipped_items: 5, skipped_details: details }))).toBe(4);
    expect(skippedNotListed(log({ skipped_items: 1, skipped_details: details }))).toBe(0);
  });
});

describe("summarizeSyncLogPage", () => {
  it("adds up successful syncs only and counts every sync on the page", () => {
    expect(
      summarizeSyncLogPage([
        log({ files_processed: 3, files_deleted: 1, pages_processed: 2 }),
        log({ status: "error", files_processed: 9 }),
        log({ files_processed: 2 })
      ])
    ).toEqual({ syncs: 3, successful: 2, files: 5, deleted: 1, pages: 2 });
  });
});
