import { describe, expect, it, vi } from "vitest";

import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";
import { createTranscriptCorrectionsController } from "./transcriptCorrectionsController.svelte";

// Every segment read through the transcript-source route carries the
// whole-source hash; a save is only attempted with it.
const SOURCE_HASH = "a".repeat(64);

function segment(index: number, text: string, speaker = "SPEAKER_00"): TranscriptSegment {
  return {
    index,
    fileIndex: 0,
    start: index * 4,
    end: index * 4 + 4,
    speaker,
    text,
    segmentsHash: SOURCE_HASH
  };
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
  speaker: "SPEAKER_02",
  decision: "confirmed" as const
};

const SPAN_EDIT = {
  segment_index: 0,
  char_start: 11,
  char_end: 17,
  original: "sugary",
  original_speaker: "SPEAKER_00",
  speaker: "SPEAKER_03",
  decision: "confirmed" as const
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

function makeController(options: { list?: unknown[]; segments?: TranscriptSegment[] } = {}) {
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
    rawSegments: options.segments ?? RAW_SEGMENTS
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

    expect(save).not.toHaveBeenCalled();
    expect(await controller.flush()).toBe(false);
  });
});

it("sends v3 source hash and preserves same-label confirmation after reload", async () => {
  const segments = RAW_SEGMENTS.map((segment) => ({
    ...segment,
    segmentsHash: "a".repeat(64),
    speakerAttribution: "provisional"
  }));
  const { controller, save } = makeController({ segments });
  await controller.load();
  expect(
    await controller.saveSpeakerEdits([
      { segment_index: 0, char_start: null, char_end: null, speaker: "SPEAKER_00" }
    ])
  ).toBe(true);
  expect(save.mock.calls[0][0]).toMatchObject({
    segmentsHash: "a".repeat(64),
    speakerEdits: [{ segment_index: 0, speaker: "SPEAKER_00", decision: "confirmed" }]
  });
  expect(controller.speakerEdits[0].decision).toBe("confirmed");
});

it("preserves a failed draft and blocks approval", async () => {
  const { controller, save } = makeController();
  await controller.load();
  save.mockRejectedValueOnce(new Error("write failed"));
  expect(
    await controller.saveSpeakerEdits([
      { segment_index: 0, char_start: null, char_end: null, speaker: null }
    ])
  ).toBe(false);
  expect(controller.speakerEdits[0].decision).toBe("unresolved");
  expect(await controller.flush()).toBe(false);
  expect(controller.error).not.toBeNull();
});

it("serializes full-list writes and approval waits for the complete queue", async () => {
  const { controller, save } = makeController();
  await controller.load();
  let release!: (value: ReturnType<typeof correctionSet>) => void;
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      })
  );
  const first = controller.saveSpeakerEdits([
    { segment_index: 0, char_start: null, char_end: null, speaker: null }
  ]);
  const second = controller.saveSpeakerEdits([
    { segment_index: 1, char_start: null, char_end: null, speaker: "SPEAKER_00" }
  ]);
  await Promise.resolve();
  expect(save).toHaveBeenCalledTimes(1);
  let finished = false;
  const flush = controller.flush().then((value) => {
    finished = true;
    return value;
  });
  await Promise.resolve();
  expect(finished).toBe(false);
  release(correctionSet({ revision: 5 }));
  expect(await first).toBe(true);
  expect(await second).toBe(true);
  expect(await flush).toBe(true);
  expect(save.mock.calls[1][0].expectedRevision).toBe(5);
  expect(save.mock.calls[1][0].speakerEdits).toHaveLength(2);
});

it("blocks queued replacements after failure and retries the latest draft with its original revision", async () => {
  const { controller, save, list } = makeController();
  await controller.load();
  save.mockRejectedValueOnce(new Error("conflict"));
  const first = controller.saveSpeakerEdits([
    { segment_index: 0, char_start: null, char_end: null, speaker: null }
  ]);
  const second = controller.saveSpeakerEdits([
    { segment_index: 1, char_start: null, char_end: null, speaker: "SPEAKER_00" }
  ]);
  expect(await first).toBe(false);
  expect(await second).toBe(false);
  expect(save).toHaveBeenCalledTimes(1);
  expect(list).toHaveBeenCalledTimes(1);
  expect(controller.speakerEdits).toHaveLength(2);
  expect(await controller.retry()).toBe(true);
  expect(save.mock.calls[1][0].expectedRevision).toBeNull();
  expect(save.mock.calls[1][0].speakerEdits).toHaveLength(2);
  expect(await controller.flush()).toBe(true);
});

it("round-trips speaker decisions after emoji using API code-point offsets", async () => {
  const segments = [
    {
      ...RAW_SEGMENTS[0],
      text: "🙂 ett två",
      speakerAttribution: "provisional",
      segmentsHash: "a".repeat(64)
    }
  ];
  const { controller, save } = makeController({ segments });
  await controller.load();
  expect(
    await controller.saveSpeakerEdits([
      { segment_index: 0, char_start: 3, char_end: 6, speaker: "SPEAKER_01" }
    ])
  ).toBe(true);
  expect(save.mock.calls[0][0].speakerEdits).toEqual([
    expect.objectContaining({ char_start: 2, char_end: 5, original: "ett" })
  ]);
  expect(controller.speakerEdits[0]).toMatchObject({ char_start: 3, char_end: 6, original: "ett" });
});

it("retries a failed initial load without overwriting existing corrections", async () => {
  const { controller, list, save } = makeController({
    list: [correctionSet({ occurrences: [OCCURRENCE] })]
  });
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  list.mockRejectedValueOnce(new Error("offline"));
  try {
    await controller.load();
    expect(controller.ready).toBe(false);
    expect(controller.error).not.toBeNull();
    expect(await controller.retry()).toBe(true);
    expect(controller.error).toBeNull();
    expect(controller.occurrences).toEqual([OCCURRENCE]);
    expect(save).not.toHaveBeenCalled();
  } finally {
    log.mockRestore();
  }
});

it("never saves segments that carry no source hash", async () => {
  const segments = RAW_SEGMENTS.map(
    ({ segmentsHash: _hash, ...rest }) => rest as TranscriptSegment
  );
  const { controller, save } = makeController({ segments });
  await controller.load();
  expect(
    await controller.saveSpeakerEdits([
      { segment_index: 0, char_start: null, char_end: null, speaker: "SPEAKER_00" }
    ])
  ).toBe(false);
  expect(save).not.toHaveBeenCalled();
});
