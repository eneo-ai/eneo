import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { reviewEditsQueryOptions } from "./review-extras-api";
import {
  activeReviewQueryOptions,
  runDetailQueryOptions,
  runEvidenceQueryOptions,
  runKeys,
  runsListQueryOptions,
  runStepsQueryOptions,
  transcriptCorrectionsQueryOptions,
  transcriptQueryOptions,
  transcriptRevisionsQueryOptions,
  transcriptWordsQueryOptions
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

describe("transcript reads", () => {
  const target = { stepId: "step-1", attemptNo: 2 };

  function cached() {
    const queryClient = new QueryClient();
    const source = transcriptQueryOptions("flow-1", "run-1", target);
    const words = transcriptWordsQueryOptions("flow-1", "run-1", target);
    queryClient.setQueryData(source.queryKey, { status: "unavailable" });
    queryClient.setQueryData(words.queryKey, null);
    const matched = (queryKey: readonly unknown[]) =>
      queryClient
        .getQueryCache()
        .findAll({ queryKey })
        .map((query) => query.queryKey);
    return { source: source.queryKey, words: words.queryKey, matched };
  }

  it("are not read again when the run's other reads are (a save of names, a stale refusal)", () => {
    expect(cached().matched(runKeys.run("flow-1", "run-1"))).toEqual([]);
  });

  it("are read again by Refresh, which invalidates their root too", () => {
    const { source, words, matched } = cached();
    expect(matched(runKeys.transcripts("flow-1", "run-1"))).toEqual(
      expect.arrayContaining([source, words])
    );
    expect(matched(runKeys.transcripts("flow-1", "run-2"))).toEqual([]);
  });

  it("name the attempt they read, the word timings too", () => {
    const words = (attemptNo: number) =>
      transcriptWordsQueryOptions("flow-1", "run-1", { stepId: "step-1", attemptNo }).queryKey;
    expect(words(1)).not.toEqual(words(2));
  });

  it("keep a finished attempt's source and word timings for good", () => {
    expect(transcriptQueryOptions("flow-1", "run-1", target).staleTime).toBe(Infinity);
    expect(transcriptWordsQueryOptions("flow-1", "run-1", target).staleTime).toBe(Infinity);
  });
});
