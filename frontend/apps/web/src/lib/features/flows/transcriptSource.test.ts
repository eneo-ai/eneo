import { describe, expect, it, vi } from "vitest";

import { loadTranscriptSource, transcriptSourceRef } from "./transcriptSource";

function client(pages: Record<number, unknown>) {
  const get = vi.fn(async ({ startSegmentIndex }: { startSegmentIndex: number }) => {
    const page = pages[startSegmentIndex];
    if (!page) throw new Error(`no page at ${startSegmentIndex}`);
    return page;
  });
  return { eneo: { flows: { runs: { transcriptSource: { get } } } } as never, get };
}

const ref = { flowId: "f", runId: "r", stepId: "s", attemptNo: 2 };

describe("loadTranscriptSource", () => {
  it("follows next_segment_index, keeps the first page's speaker review and stamps the hash", async () => {
    const { eneo, get } = client({
      0: {
        status: "present",
        source_hash: "h".repeat(64),
        start_segment_index: 0,
        page_size: 2,
        next_segment_index: 2,
        speaker_review: {
          files: [
            {
              file_index: 0,
              overlap_detection: "detected",
              overlaps: [{ id: "o1", start: 1, end: 2, detected_speaker_count: 2 }]
            }
          ]
        },
        segments: [
          {
            segment_index: 0,
            file_index: 0,
            start: 0,
            end: 1,
            speaker: "SPEAKER_00",
            text: "Hej."
          },
          {
            segment_index: 1,
            file_index: 0,
            start: 1,
            end: 2,
            speaker: "SPEAKER_01",
            text: "Ja.",
            overlap_ids: ["o1"]
          }
        ]
      },
      2: {
        status: "present",
        source_hash: "h".repeat(64),
        start_segment_index: 2,
        page_size: 2,
        next_segment_index: null,
        segments: [
          { segment_index: 2, file_index: 0, start: 2, end: 3, speaker: null, text: "(paus)" }
        ]
      }
    });
    const loaded = await loadTranscriptSource(eneo, ref);
    expect(get).toHaveBeenCalledTimes(2);
    expect(get.mock.calls[1][0]).toMatchObject({ ...ref, startSegmentIndex: 2 });
    expect(loaded.status).toBe("present");
    if (loaded.status !== "present") return;
    expect(loaded.segments.map((s) => s.index)).toEqual([0, 1, 2]);
    expect(loaded.segments[1].overlaps).toEqual([
      { id: "o1", start: 1, end: 2, detected_speaker_count: 2 }
    ]);
    expect(loaded.segments.every((s) => s.segmentsHash === "h".repeat(64))).toBe(true);
    expect(loaded.speakerReviews).toHaveLength(1);
    expect(loaded.sourceHash).toBe("h".repeat(64));
  });

  it("reports omitted and pre-row sources without segments", async () => {
    const omitted = await loadTranscriptSource(
      client({ 0: { status: "omitted", reason: 1, bounds: {} } }).eneo,
      ref
    );
    expect(omitted).toEqual({ status: "omitted", reason: 1 });
    const preRow = await loadTranscriptSource(
      client({ 0: { status: "unavailable_pre_row" } }).eneo,
      ref
    );
    expect(preRow).toEqual({ status: "unavailable_pre_row" });
  });

  it("refuses a page that does not advance", async () => {
    const { eneo } = client({
      0: { status: "present", source_hash: "h".repeat(64), next_segment_index: 0, segments: [] }
    });
    await expect(loadTranscriptSource(eneo, ref)).rejects.toThrow(/did not advance/);
  });
});

describe("transcriptSourceRef", () => {
  it("reads the attempt the step metadata names", () => {
    expect(transcriptSourceRef({ source: { attempt_no: 3 } }, "step")).toEqual({
      stepId: "step",
      attemptNo: 3
    });
    expect(transcriptSourceRef({ source: { attempt_no: 0 } }, "step")).toBeNull();
    expect(transcriptSourceRef({}, "step")).toBeNull();
    expect(transcriptSourceRef({ source: { attempt_no: 1 } }, null)).toBeNull();
  });
});
