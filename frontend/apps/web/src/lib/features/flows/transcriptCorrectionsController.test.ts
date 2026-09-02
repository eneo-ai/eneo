import { describe, expect, it, vi } from "vitest";

import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";
import { createTranscriptCorrectionsController } from "./transcriptCorrectionsController.svelte";

function segment(index: number, text: string, speaker = "SPEAKER_00"): TranscriptSegment {
  return { index, fileIndex: 0, start: index * 4, end: index * 4 + 4, speaker, text };
}

const RAW_SEGMENTS = [
  segment(0, "Vi frågade sugary om planen."),
  segment(1, "sugary svarade direkt.", "SPEAKER_01")
];

const OCCURRENCE = {
  segment_index: 0,
  char_start: 11,
  char_end: 17,
  original: "sugary",
  corrected: "Çagri"
};

const WHOLE_EDIT = {
  segment_index: 1,
  char_start: null,
  char_end: null,
  original: null,
  original_speaker: "SPEAKER_01",
  speaker: "SPEAKER_02"
};

const SPAN_EDIT = {
  segment_index: 0,
  char_start: 11,
  char_end: 17,
  original: "sugary",
  original_speaker: "SPEAKER_00",
  speaker: "SPEAKER_03"
};

function correctionSet(partial: Record<string, unknown> = {}) {
  return {
    flow_run_id: "run-1",
    step_id: "step-1",
    occurrences: [],
    speaker_edits: [],
    revision: 1,
    stale: false,
    edited_by_principal_type: "user",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    ...partial
  };
}

function makeController(options: { list?: unknown[] } = {}) {
  const list = vi.fn(async () => options.list ?? []);
  const save = vi.fn(async (args: Record<string, unknown>) =>
    correctionSet({
      revision: 2,
      occurrences: args.occurrences,
      speaker_edits: args.speakerEdits
    })
  );
  const eneo = { flows: { runs: { transcriptCorrections: { list, save } } } };
  const controller = createTranscriptCorrectionsController({
    eneo: eneo as never,
    flowId: "flow-1",
    runId: "run-1",
    stepId: "step-1",
    rawSegments: RAW_SEGMENTS
  });
  return { controller, list, save };
}

describe("transcriptCorrectionsController speaker edits", () => {
  it("seats stored speaker edits on load", async () => {
    const { controller } = makeController({
      list: [correctionSet({ speaker_edits: [WHOLE_EDIT], revision: 3 })]
    });

    await controller.load();

    expect(controller.ready).toBe(true);
    expect(controller.speakerEdits).toEqual([WHOLE_EDIT]);
  });

  it("normalizes and anchors reassignments in one replace-style save", async () => {
    const { controller, save } = makeController({ list: [correctionSet()] });
    await controller.load();

    const accepted = await controller.saveSpeakerEdits([
      { segment_index: 1, char_start: 0, char_end: 22, speaker: "SPEAKER_02" }
    ]);

    expect(accepted).toBe(true);
    expect(save).toHaveBeenCalledTimes(1);
    const body = save.mock.calls[0][0] as Record<string, unknown>;
    expect(body.expectedRevision).toBe(1);
    expect(body.occurrences).toEqual([]);
    // Full coverage serializes as a whole-segment edit with filled anchors.
    expect(body.speakerEdits).toEqual([WHOLE_EDIT]);
    expect(controller.speakerEdits).toEqual([WHOLE_EDIT]);
  });

  it("threads stored speaker edits through a text-line save", async () => {
    const { controller, save } = makeController({
      list: [correctionSet({ speaker_edits: [WHOLE_EDIT] })]
    });
    await controller.load();

    await controller.saveLine(0, "Vi frågade sugary om planerna.");

    const body = save.mock.calls[0][0] as Record<string, unknown>;
    expect(body.speakerEdits).toEqual([WHOLE_EDIT]);
    expect(body.occurrences).toHaveLength(1);
  });

  it("reverts one edit by its raw anchor", async () => {
    const { controller, save } = makeController({
      list: [correctionSet({ speaker_edits: [SPAN_EDIT, WHOLE_EDIT] })]
    });
    await controller.load();

    await controller.revertSpeakerEdit(1, null);

    const body = save.mock.calls[0][0] as Record<string, unknown>;
    expect(body.speakerEdits).toEqual([SPAN_EDIT]);
  });

  it("never carries stale edits into a save and counts them", async () => {
    const { controller, save } = makeController({
      list: [
        correctionSet({
          stale: true,
          occurrences: [OCCURRENCE],
          speaker_edits: [WHOLE_EDIT]
        })
      ]
    });
    await controller.load();

    expect(controller.speakerEdits).toEqual([]);
    expect(controller.staleCount).toBe(2);

    await controller.saveSpeakerEdits([
      { segment_index: 0, char_start: 11, char_end: 17, speaker: "SPEAKER_05" }
    ]);

    const body = save.mock.calls[0][0] as Record<string, unknown>;
    expect(body.occurrences).toEqual([]);
    expect(body.speakerEdits).toEqual([
      {
        segment_index: 0,
        char_start: 11,
        char_end: 17,
        original: "sugary",
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_05"
      }
    ]);
  });
});
