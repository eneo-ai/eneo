import type { IntegrationKnowledge } from "../knowledge";
import { describe, expect, it } from "vitest";
import {
  activityKind,
  appendPage,
  continueWindow,
  groupActivityByDay,
  itemsToPage,
  mergeActivity,
  mergeFirstPage,
  readSyncLogExtras,
  skippedNotListed,
  summarizeActivity
} from "./sync-activity";
import type { SyncLog } from "./queries";

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

const itemA = { id: "a", name: "A" } as IntegrationKnowledge;
const itemB = { id: "b", name: "B" } as IntegrationKnowledge;

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
    ).toEqual({
      unchangedItems: 7,
      changedFiles: [],
      changedTotal: 0,
      skippedTruncated: true,
      reconcileWarning: "Delta token reset"
    });
  });

  it("defaults for syncs recorded before the fields existed", () => {
    expect(readSyncLogExtras(log({ metadata: null }))).toEqual({
      unchangedItems: 0,
      changedFiles: [],
      changedTotal: 0,
      skippedTruncated: false,
      reconcileWarning: null
    });
  });
});

describe("the changed files of a sync", () => {
  it("keeps the well-formed entries and the total the cap leaves out", () => {
    const extras = readSyncLogExtras(
      log({
        metadata: {
          changed_details: [
            { file: "a.pdf", change: "added" },
            { file: "b.pdf", change: "renamed" },
            { file: "c.pdf", change: "deleted" },
            "garbage"
          ],
          changed_total: 70
        } as SyncLog["metadata"]
      })
    );
    expect(extras.changedFiles).toEqual([
      { file: "a.pdf", change: "added" },
      { file: "c.pdf", change: "deleted" }
    ]);
    expect(extras.changedTotal).toBe(70);
  });
});

describe("skippedNotListed", () => {
  it("is the skipped count minus the listed details, never negative", () => {
    const details = [{ file: "a", reason: "r" }];
    expect(skippedNotListed(log({ skipped_items: 5, skipped_details: details }))).toBe(4);
    expect(skippedNotListed(log({ skipped_items: 1, skipped_details: details }))).toBe(0);
  });
});

describe("activityKind", () => {
  it.each([
    [{ status: "error", files_processed: 3 }, "failed"],
    [{ status: "in_progress" }, "running"],
    [{ files_deleted: 1 }, "changed"],
    [{ skipped_items: 2 }, "changed"],
    [{}, "unchanged"]
  ] as const)("%o → %s", (overrides, kind) => {
    expect(activityKind(log(overrides))).toBe(kind);
  });
});

describe("the activity timeline", () => {
  const entries = mergeActivity([
    { item: itemA, logs: [log({ id: "a1", started_at: "2026-10-13T08:00:00" })] },
    {
      item: itemB,
      logs: [
        log({ id: "b1", started_at: "2026-10-13T18:00:00", status: "error" }),
        log({ id: "b2", started_at: "2026-10-12T09:00:00", files_processed: 4, files_deleted: 1 })
      ]
    }
  ]);

  it("stops where a partly loaded item runs out, so no item's syncs go missing", () => {
    const partial = mergeActivity([
      {
        item: itemA,
        logs: [log({ id: "a1", started_at: "2026-10-13T08:00:00" })],
        total: 5
      },
      {
        item: itemB,
        logs: [
          log({ id: "b1", started_at: "2026-10-13T18:00:00" }),
          log({ id: "b2", started_at: "2026-10-12T09:00:00" })
        ],
        total: 2
      }
    ]);
    expect(partial.map((entry) => entry.log.id)).toEqual(["b1", "a1"]);
  });

  it("merges every item's logs newest first", () => {
    expect(entries.map((entry) => [entry.log.id, entry.item.id])).toEqual([
      ["b1", "b"],
      ["a1", "a"],
      ["b2", "b"]
    ]);
  });

  it("groups by local day in order", () => {
    expect(
      groupActivityByDay(entries).map((day) => [day.day, day.entries.map((e) => e.log.id)])
    ).toEqual([
      ["2026-10-13", ["b1", "a1"]],
      ["2026-10-12", ["b2"]]
    ]);
  });

  it("totals the syncs, failures and changes", () => {
    expect(summarizeActivity(entries)).toEqual({
      syncs: 3,
      failed: 1,
      changedFiles: 4,
      unchanged: 0,
      deleted: 1
    });
  });
});

describe("paging an item's logs", () => {
  const ids = (logs: SyncLog[]) => logs.map((entry) => entry.id);
  const logs = (...names: string[]) => names.map((id) => log({ id }));

  it("puts a reloaded first page above the older pages it reaches", () => {
    expect(ids(mergeFirstPage(logs("l3", "l2", "l1"), logs("l4", "l3"), 20))).toEqual([
      "l4",
      "l3",
      "l2",
      "l1"
    ]);
  });

  it("starts over when more syncs ran than the first page holds", () => {
    expect(ids(mergeFirstPage(logs("l2", "l1"), logs("l9", "l8"), 20))).toEqual(["l9", "l8"]);
  });

  it("takes a first page that holds every log as it is", () => {
    expect(ids(mergeFirstPage(logs("l2", "gone"), logs("l3", "l2"), 2))).toEqual(["l3", "l2"]);
  });

  it("takes the first page as it is when nothing was loaded before", () => {
    expect(ids(mergeFirstPage(undefined, logs("l2", "l1"), 20))).toEqual(["l2", "l1"]);
  });

  it("appends an older page without the logs a newer sync pushed into it", () => {
    expect(ids(appendPage(logs("l5", "l4"), logs("l4", "l3")))).toEqual(["l5", "l4", "l3"]);
  });
});

describe("continueWindow", () => {
  const logs = (...names: string[]) => names.map((id) => log({ id }));
  const window = (...names: string[]) => ({ logs: logs(...names), total: 30 });
  const page = (...names: string[]) => ({ items: logs(...names), total_count: 30 });
  const ids = (result: ReturnType<typeof continueWindow>) => result?.logs.map((entry) => entry.id);

  it("continues a window that still ends where the page was asked from", () => {
    // A new revision's first page put a newer sync above the same end.
    expect(ids(continueWindow(window("l9", "l8", "l7"), page("l6", "l5"), "l7"))).toEqual([
      "l9",
      "l8",
      "l7",
      "l6",
      "l5"
    ]);
  });

  it("continues a window whose end the page repeats, without the repeats", () => {
    expect(ids(continueWindow(window("l9", "l8"), page("l8", "l7"), "l9"))).toEqual([
      "l9",
      "l8",
      "l7"
    ]);
  });

  it("drops a page that would leave a gap below a new revision's first page", () => {
    expect(continueWindow(window("l20", "l19"), page("l6", "l5"), "l7")).toBeNull();
  });

  it("stops paging when a page adds nothing", () => {
    expect(continueWindow(window("l9", "l8"), page(), "l8")).toEqual({
      logs: logs("l9", "l8"),
      total: 2
    });
  });
});

describe("itemsToPage", () => {
  const at = (id: string, startedAt: string) => log({ id, started_at: startedAt });

  it("pages only the folders that hold the timeline's cutoff, and those not loaded yet", () => {
    const busy = {
      item: itemA,
      total: 30,
      logs: [at("a2", "2026-10-10T10:00:00Z"), at("a1", "2026-10-09T10:00:00Z")]
    };
    const quiet = { item: itemB, total: 5, logs: [at("b1", "2026-10-01T10:00:00Z")] };
    const fresh = { item: { id: "c", name: "C" } as IntegrationKnowledge, total: 3, logs: [] };
    const complete = {
      item: { id: "d", name: "D" } as IntegrationKnowledge,
      total: 1,
      logs: [at("d1", "2026-10-11T10:00:00Z")]
    };

    // The quiet folder's older syncs sit below the busy one's oldest loaded sync: paging
    // it would show nothing until the busy folder is loaded back that far.
    expect(itemsToPage([busy, quiet, fresh, complete]).map((source) => source.item.id)).toEqual([
      "a",
      "c"
    ]);
    expect(itemsToPage([quiet, complete]).map((source) => source.item.id)).toEqual(["b"]);
    expect(itemsToPage([complete])).toEqual([]);
  });
});
