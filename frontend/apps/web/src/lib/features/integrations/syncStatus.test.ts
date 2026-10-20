import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { aggregateIntegrationSync, summarizeIntegrationSync } from "./syncStatus";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function item(name: string, metadata: Partial<Metadata>): IntegrationKnowledge {
  return { name, metadata: { size: 0, ...metadata } } as IntegrationKnowledge;
}

describe("summarizeIntegrationSync", () => {
  it.each([
    ["never", { last_sync_status: "never", document_count: 0 }, "never"],
    ["success with documents", { last_sync_status: "success", document_count: 3 }, "success"],
    ["success without documents", { last_sync_status: "success", document_count: 0 }, "empty"],
    ["error", { last_sync_status: "error", last_sync_error: "boom", document_count: 2 }, "error"],
    [
      "legacy row with a timestamp but no status",
      { last_synced_at: "2026-10-01T10:00:00Z", document_count: 4 },
      "success"
    ]
  ] as const)("maps %s", (_label, metadata, state) => {
    expect(summarizeIntegrationSync(item("x", metadata)).state).toBe(state);
  });

  it("keeps the error text and the last successful sync of a failed item", () => {
    const summary = summarizeIntegrationSync(
      item("x", {
        last_sync_status: "error",
        last_sync_error: " Token expired ",
        last_synced_at: "2026-10-01T10:00:00Z",
        last_sync_attempted_at: "2026-10-02T10:00:00Z"
      })
    );
    expect(summary.errors).toEqual([{ itemName: null, message: "Token expired" }]);
    expect(summary.lastSyncedAt).toBe("2026-10-01T10:00:00Z");
    expect(summary.lastSyncAttemptedAt).toBe("2026-10-02T10:00:00Z");
  });
});

describe("aggregateIntegrationSync", () => {
  it("is an error naming the failed items when any child failed", () => {
    const summary = aggregateIntegrationSync([
      item("Policies", { last_sync_status: "success", document_count: 5 }),
      item("Archive", { last_sync_status: "error", last_sync_error: "403" }),
      item("Drafts", { last_sync_status: "error", last_sync_error: "timeout" })
    ]);
    expect(summary.state).toBe("error");
    expect(summary.errors).toEqual([
      { itemName: "Archive", message: "403" },
      { itemName: "Drafts", message: "timeout" }
    ]);
    expect(summary.documentCount).toBe(5);
  });

  it("adds the documents up and keeps the latest successful sync otherwise", () => {
    const summary = aggregateIntegrationSync([
      item("A", {
        last_sync_status: "success",
        document_count: 2,
        last_synced_at: "2026-10-01T10:00:00Z"
      }),
      item("B", { last_sync_status: "never", document_count: 0 }),
      item("C", {
        last_sync_status: "success",
        document_count: 3,
        last_synced_at: "2026-10-03T10:00:00Z"
      })
    ]);
    expect(summary).toMatchObject({
      state: "success",
      documentCount: 5,
      lastSyncedAt: "2026-10-03T10:00:00Z",
      errors: []
    });
  });

  it.each([
    ["no items", [], "never"],
    ["only unsynced items", [item("A", { last_sync_status: "never" })], "never"],
    [
      "synced items without documents",
      [item("A", { last_sync_status: "success", document_count: 0 })],
      "empty"
    ]
  ] as const)("is %s → %s", (_label, items, state) => {
    expect(aggregateIntegrationSync([...items]).state).toBe(state);
  });
});
