import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { reviewEditsQueryOptions } from "./review-extras-api";
import {
  activeReviewQueryOptions,
  getTranscriptSource,
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

describe("transcript source paging", () => {
  const target = { stepId: "step-1", attemptNo: 1 };
  type Call = { start: number; signal: AbortSignal | undefined };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function segment(index: number) {
    return {
      segment_index: index,
      file_index: 0,
      start: index,
      end: index + 1,
      speaker: null,
      text: `line ${index}`
    };
  }

  /**
   * A stored source of `total` lines served `pageSize` at a time. `answer`
   * says how a page at `start` answers: after how many ms, or never (null),
   * and with which status; `page` may rewrite a page's body. A stopped
   * request rejects with its signal's reason, or with a bare AbortError when
   * `bareAbort` is set, as a browser may for a body still being read.
   */
  function serve(
    total: number,
    pageSize: number,
    {
      answer = () => ({ delayMs: 0 }),
      page = (body) => body,
      bareAbort = false
    }: {
      answer?: (start: number) => { delayMs: number | null; status?: number };
      page?: (body: Record<string, unknown>, start: number) => Record<string, unknown>;
      bareAbort?: boolean;
    } = {}
  ) {
    const calls: Call[] = [];
    let inFlight = 0;
    let maxInFlight = 0;
    vi.spyOn(browserApi, "GET").mockImplementation(((
      _path: string,
      init: { params: { query: { start_segment_index: number } }; signal?: AbortSignal }
    ) => {
      const start = init.params.query.start_segment_index;
      const signal = init.signal;
      calls.push({ start, signal });
      const end = Math.min(start + pageSize, total);
      const body = page(
        {
          status: "present",
          run_id: "run-1",
          step_id: "step-1",
          attempt_no: 1,
          source_hash: `hash-at-${start}`,
          bounds: {
            segments_bytes: 1,
            detail_bytes: 0,
            words_bytes: 0,
            segments_count: total,
            words_count: 0
          },
          component_omissions: {},
          start_segment_index: start,
          page_size: pageSize,
          max_response_bytes: 1_000_000,
          next_segment_index: end < total ? end : null,
          segments: Array.from({ length: Math.max(end - start, 0) }, (_, i) => segment(start + i)),
          speaker_review: start === 0 ? { files: [] } : null
        },
        start
      );
      const { delayMs, status = 200 } = answer(start);
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      return new Promise((resolve, reject) => {
        const timer =
          delayMs === null
            ? undefined
            : setTimeout(() => {
                inFlight -= 1;
                const response = new Response(JSON.stringify(body), { status });
                resolve(status < 400 ? { data: body, response } : { error: body, response });
              }, delayMs);
        signal?.addEventListener(
          "abort",
          () => {
            clearTimeout(timer);
            inFlight -= 1;
            reject(
              bareAbort
                ? new DOMException("The operation was aborted.", "AbortError")
                : signal.reason
            );
          },
          { once: true }
        );
      });
    }) as never);
    return { calls, maxInFlight: () => maxInFlight };
  }

  it("reads a single-page source with one request", async () => {
    const { calls } = serve(150, 200);
    const source = await getTranscriptSource("flow-1", "run-1", target);
    expect(calls.map((call) => call.start)).toEqual([0]);
    expect(source.status === "present" && source.segments).toHaveLength(150);
  });

  it("reads the remaining pages a few at a time, at the page size the server returned, and assembles them in order", async () => {
    // Later pages answer sooner, so they arrive out of order.
    const { calls, maxInFlight } = serve(2_000, 150, {
      answer: (start) => ({ delayMs: start === 0 ? 0 : Math.round((2_000 - start) / 50) })
    });
    const source = await getTranscriptSource("flow-1", "run-1", target);
    if (source.status !== "present") throw new Error(source.status);
    expect(source.segments.map((line) => line.segment_index)).toEqual(
      Array.from({ length: 2_000 }, (_, i) => i)
    );
    expect(calls.map((call) => call.start).sort((a, b) => a - b)).toEqual(
      Array.from({ length: 14 }, (_, i) => i * 150)
    );
    expect(maxInFlight()).toBe(3);
    // The first page's hash and speaker review are kept, as before.
    expect(source.sourceHash).toBe("hash-at-0");
    expect(source.speakerReview).toEqual({ files: [] });
  });

  it("follows next_segment_index past the line count it planned for", async () => {
    const { calls } = serve(500, 200, {
      page: (body) => ({ ...body, bounds: { ...(body.bounds as object), segments_count: 300 } })
    });
    const source = await getTranscriptSource("flow-1", "run-1", target);
    expect(source.status === "present" && source.segments).toHaveLength(500);
    expect(calls.map((call) => call.start)).toEqual([0, 200, 400]);
  });

  it("fails the whole read when one page fails, stops the requests still out and starts no other", async () => {
    const { calls } = serve(2_000, 200, {
      answer: (start) =>
        start === 400 ? { delayMs: 5, status: 500 } : { delayMs: start === 0 ? 0 : null }
    });
    await expect(getTranscriptSource("flow-1", "run-1", target)).rejects.toBeInstanceOf(
      EneoApiError
    );
    // The failed page's slot is not handed to a page queued behind it.
    expect(calls.map((call) => call.start)).toEqual([0, 200, 400, 600]);
    expect(calls.every((call) => call.signal?.aborted)).toBe(true);
  });

  it("fails with the failed page's error when the pages it stops reject with a bare abort", async () => {
    // Page 200 is still out when page 400 fails: the read waits on page 200,
    // which the abort ends with a bare AbortError, not the 503 behind it.
    serve(2_000, 200, {
      answer: (start) =>
        start === 400 ? { delayMs: 5, status: 503 } : { delayMs: start === 0 ? 0 : null },
      bareAbort: true
    });
    const failure = await getTranscriptSource("flow-1", "run-1", target).catch(
      (error: unknown) => error
    );
    expect(failure).toBeInstanceOf(EneoApiError);
    expect((failure as EneoApiError).status).toBe(503);
  });

  it("stops the pages requested in advance that the read did not reach", async () => {
    // The first page says there are more lines than the source has: the read
    // ends at 300, and the pages planned past it never answer.
    const { calls } = serve(300, 100, {
      answer: (start) => ({ delayMs: start < 300 ? 0 : null }),
      page: (body) => ({ ...body, bounds: { ...(body.bounds as object), segments_count: 1_000 } })
    });
    const source = await getTranscriptSource("flow-1", "run-1", target);
    expect(source.status === "present" && source.segments).toHaveLength(300);
    const beyond = calls.filter((call) => call.start >= 300);
    expect(beyond.length).toBeGreaterThan(0);
    expect(beyond.every((call) => call.signal?.aborted)).toBe(true);
    const started = calls.length;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(calls).toHaveLength(started);
  });

  it("stops every outstanding request when the query is cancelled", async () => {
    const { calls } = serve(2_000, 200, {
      answer: (start) => ({ delayMs: start === 0 ? 0 : null })
    });
    const controller = new AbortController();
    const read = getTranscriptSource("flow-1", "run-1", target, controller.signal);
    await vi.waitFor(() => expect(calls).toHaveLength(4));
    controller.abort();
    await expect(read).rejects.toMatchObject({ name: "AbortError" });
    expect(calls).toHaveLength(4);
    expect(calls.every((call) => call.signal?.aborted)).toBe(true);
  });

  it("refuses a page that does not advance", async () => {
    serve(600, 200, {
      page: (body, start) => (start === 200 ? { ...body, next_segment_index: 200 } : body)
    });
    await expect(getTranscriptSource("flow-1", "run-1", target)).rejects.toThrow(
      "Transcript source paging did not advance"
    );
  });

  it("refuses a first page that does not advance before requesting any other", async () => {
    const { calls } = serve(600, 200, {
      page: (body, start) => (start === 0 ? { ...body, next_segment_index: 0 } : body)
    });
    await expect(getTranscriptSource("flow-1", "run-1", target)).rejects.toThrow(
      "Transcript source paging did not advance"
    );
    expect(calls.map((call) => call.start)).toEqual([0]);
  });
});
