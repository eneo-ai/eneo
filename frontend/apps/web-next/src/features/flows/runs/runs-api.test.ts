import { describe, expect, it } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { reviewEditsQueryOptions } from "./review-extras-api";
import {
  activeReviewQueryOptions,
  runDetailQueryOptions,
  runEvidenceQueryOptions,
  runsListQueryOptions,
  runStepsQueryOptions,
  transcriptCorrectionsQueryOptions,
  transcriptRevisionsQueryOptions
} from "./runs-api";

const checkpoint = { flow_id: "flow-1", flow_run_id: "run-1", id: "checkpoint-1", revision: 1 };

function content(settled: boolean) {
  return [
    runStepsQueryOptions("flow-1", "run-1", "v1", settled),
    runEvidenceQueryOptions("flow-1", "run-1", settled)
  ];
}

describe("audited reads", () => {
  it("keep the run detail, read once per version of the run, for good", () => {
    expect(runDetailQueryOptions(browserApi, "flow-1", "run-1", "v1").staleTime).toBe(Infinity);
  });

  it("keep a settled run's content for good: nothing changes it any more", () => {
    for (const options of content(true)) {
      expect(options.staleTime, String(options.queryKey)).toBe(Infinity);
    }
  });

  it("name in the evidence's key whether the run had settled when it was read", () => {
    expect(runEvidenceQueryOptions("flow-1", "run-1", true).queryKey).not.toEqual(
      runEvidenceQueryOptions("flow-1", "run-1", false).queryKey
    );
  });

  it("leave a live run's content, an open review and transcript corrections on the app's default", () => {
    // A review edit or approval changes them without moving the run's progress;
    // corrections are saved, and speakers named, on a settled run too.
    for (const options of [
      ...content(false),
      activeReviewQueryOptions("flow-1", "run-1", "v1"),
      reviewEditsQueryOptions(checkpoint),
      transcriptCorrectionsQueryOptions("flow-1", "run-1"),
      transcriptRevisionsQueryOptions("flow-1", "run-1", "step-1")
    ]) {
      expect(options.staleTime, String(options.queryKey)).toBeUndefined();
    }
  });

  it("do not keep the evidence bundle once nothing shows it", () => {
    expect(runEvidenceQueryOptions("flow-1", "run-1", true).gcTime).toBe(60_000);
  });

  it("leave the content-free list on the app's default", () => {
    expect(runsListQueryOptions("flow-1").staleTime).toBeUndefined();
  });
});
