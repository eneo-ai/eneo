import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { beforeEach, describe, expect, it } from "vitest";
import {
  describeImportOutcome,
  pendingImports,
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
