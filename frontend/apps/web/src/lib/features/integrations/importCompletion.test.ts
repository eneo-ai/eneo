import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { beforeEach, describe, expect, it } from "vitest";
import {
  PENDING_IMPORTS_STORAGE_KEY,
  createPendingImports,
  describeImportOutcome,
  pendingImports,
  reportableImports,
  settledImports,
  trackImports,
  untrackImports,
  type PendingImport
} from "./importCompletion";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(metadata: Partial<Metadata>): IntegrationKnowledge {
  return {
    id: "ik-1",
    name: "Protokoll 2026",
    metadata: { size: 0, ...metadata }
  } as IntegrationKnowledge;
}

function pending(jobId: string): PendingImport {
  return { jobId, knowledgeId: `ik-${jobId}`, name: jobId, spaceRouteId: "space-1" };
}

function fakeStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => void entries.set(key, value),
    removeItem: (key) => void entries.delete(key),
    clear: () => entries.clear(),
    key: () => null,
    get length() {
      return entries.size;
    }
  };
}

describe("pending imports", () => {
  beforeEach(() => pendingImports.set([]));

  it("tracks each job once and forgets it on request", () => {
    trackImports([pending("a"), pending("b")]);
    trackImports([pending("b")]);
    expect(get(pendingImports).map((item) => item.jobId)).toEqual(["a", "b"]);
    untrackImports(["a"]);
    expect(get(pendingImports).map((item) => item.jobId)).toEqual(["b"]);
  });

  it("settles jobs that completed, failed or vanished, not running ones", () => {
    const settled = settledImports(
      [pending("a"), pending("b"), pending("c"), pending("d")],
      [
        { id: "a", status: "in progress" },
        { id: "b", status: "complete" },
        { id: "c", status: "failed" }
      ]
    );
    expect(settled.map((item) => item.jobId)).toEqual(["b", "c", "d"]);
  });

  it("does not count a missing job as finished before the job list has loaded", () => {
    const items = [pending("a"), pending("b")];
    const jobs = [{ id: "a", status: "complete" as const }];
    expect(settledImports(items, jobs, false).map((item) => item.jobId)).toEqual(["a"]);
    expect(settledImports(items, jobs, true).map((item) => item.jobId)).toEqual(["a", "b"]);
  });

  it("restores the imports an earlier page load stored and clears them once reported", () => {
    const storage = fakeStorage();
    createPendingImports(storage).set([pending("a")]);

    const restored = createPendingImports(storage);
    expect(get(restored)).toEqual([pending("a")]);

    restored.set([]);
    expect(storage.getItem(PENDING_IMPORTS_STORAGE_KEY)).toBeNull();
  });

  it("starts empty when the stored list is unreadable or storage is unavailable", () => {
    const garbage = fakeStorage();
    garbage.setItem(PENDING_IMPORTS_STORAGE_KEY, "{not json");
    expect(get(createPendingImports(garbage))).toEqual([]);

    const partial = fakeStorage();
    partial.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([{ jobId: "a" }, pending("b")]));
    expect(get(createPendingImports(partial))).toEqual([pending("b")]);

    const blocked: Storage = {
      ...fakeStorage(),
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      }
    };
    const store = createPendingImports(blocked);
    store.set([pending("c")]);
    expect(get(store)).toEqual([pending("c")]);
    expect(get(createPendingImports(null))).toEqual([]);
  });
});

describe("reportableImports", () => {
  const batch = (jobId: string): PendingImport => ({
    ...pending(jobId),
    batchId: "b1",
    batchName: "Nämnder"
  });

  it("gives an import on its own its own notice", () => {
    expect(reportableImports([pending("a"), pending("b")], [pending("b")])).toEqual([
      [pending("b")]
    ]);
  });

  it("holds a batch back until all of it has settled, then gives it one notice", () => {
    const all = [batch("a"), batch("b"), batch("c"), pending("d")];
    expect(reportableImports(all, [batch("a"), batch("c")])).toEqual([]);
    expect(reportableImports(all, [batch("a"), batch("b"), batch("c"), pending("d")])).toEqual([
      [batch("a"), batch("b"), batch("c")],
      [pending("d")]
    ]);
  });

  it("restores a batch an earlier page load stored", () => {
    const storage = fakeStorage();
    createPendingImports(storage).set([batch("a")]);
    expect(get(createPendingImports(storage))).toEqual([batch("a")]);

    storage.setItem(
      PENDING_IMPORTS_STORAGE_KEY,
      JSON.stringify([{ ...pending("x"), batchId: 7 }, batch("y")])
    );
    expect(get(createPendingImports(storage))).toEqual([batch("y")]);
  });
});

describe("describeImportOutcome", () => {
  it("reads the indexed and skipped counts from the sync summary", () => {
    const outcome = describeImportOutcome(
      knowledge({
        last_sync_status: "success",
        document_count: 12,
        last_sync_summary: {
          files_processed: 10,
          unchanged_items: 2,
          skipped_items: 2,
          skipped_total: 5
        }
      }),
      "space-1"
    );
    expect(outcome).toEqual({
      name: "Protokoll 2026",
      indexed: 12,
      skipped: 5,
      href: "/spaces/space-1/knowledge/integrations/ik-1",
      error: null,
      synced: true
    });
  });

  it("links to the problems tab when files were skipped and nothing was indexed", () => {
    const outcome = describeImportOutcome(
      knowledge({
        last_sync_status: "success",
        document_count: 0,
        last_sync_summary: { files_processed: 0, skipped_items: 3 }
      }),
      "space-1"
    );
    expect(outcome.indexed).toBe(0);
    expect(outcome.skipped).toBe(3);
    expect(outcome.href).toBe("/spaces/space-1/knowledge/integrations/ik-1?tab=problems");
  });

  it("falls back to the document count when the summary is missing", () => {
    const outcome = describeImportOutcome(
      knowledge({ last_sync_status: "success", document_count: 7 }),
      "space-1"
    );
    expect(outcome).toMatchObject({ indexed: 7, skipped: 0, synced: true });
  });

  it("carries the sync error and knows when nothing has synced yet", () => {
    expect(
      describeImportOutcome(
        knowledge({ last_sync_status: "error", last_sync_error: "Token expired" }),
        "space-1"
      )
    ).toMatchObject({ error: "Token expired", synced: true });
    expect(
      describeImportOutcome(knowledge({ last_sync_status: "never" }), "space-1")
    ).toMatchObject({ synced: false, error: null });
  });
});
