import { describe, expect, it } from "vitest";
import { makeRunStep } from "./run-fixtures";
import {
  clockTime,
  parseSegments,
  shownSegments,
  speakerLabels,
  speakerNamesRequest,
  transcriptTargets,
  type TranscriptCorrections,
  type TranscriptSourceSegment
} from "./transcript";

const raw: TranscriptSourceSegment[] = [
  {
    segment_index: 0,
    file_index: 0,
    start: 0,
    end: 4.2,
    speaker: "SPEAKER_00",
    text: "Välkomna till mötet."
  },
  {
    segment_index: 1,
    file_index: 0,
    start: 4.2,
    end: 9,
    speaker: "SPEAKER_01",
    text: "Tack, vi börjar med budgeten."
  },
  { segment_index: 2, file_index: 0, start: 9, end: 12, speaker: "SPEAKER_00", text: "Bra." }
];

function corrections(overrides: Partial<TranscriptCorrections> = {}): TranscriptCorrections {
  return {
    created_at: "2026-10-21T09:00:00Z",
    updated_at: "2026-10-21T09:00:00Z",
    edited_by_principal_type: "user",
    flow_run_id: "run-1",
    step_id: "step-1",
    revision: 2,
    schema_version: 3,
    segments_hash: "hash-1",
    occurrences: [],
    speaker_edits: [],
    speaker_names: {},
    stale: false,
    ...overrides
  };
}

describe("transcriptTargets", () => {
  it("finds the steps that transcribed audio and the attempt that owns the transcript", () => {
    const steps = [
      makeRunStep(2, { step_id: "step-2" }),
      makeRunStep(1, {
        step_id: "step-1",
        input_payload_json: { transcription: { file_ids: ["f1"], source: { attempt_no: 2 } } }
      }),
      makeRunStep(3, { input_payload_json: { transcription: { file_ids: [], source: {} } } })
    ];
    expect(transcriptTargets(steps)).toEqual([
      { stepId: "step-1", stepOrder: 1, attemptNo: 2, fileIds: ["f1"] }
    ]);
  });
});

describe("parseSegments", () => {
  it("reads lines with times, speaker and text", () => {
    expect(parseSegments(raw)[1]).toEqual({
      index: 1,
      fileIndex: 0,
      start: 4.2,
      end: 9,
      speaker: "SPEAKER_01",
      text: "Tack, vi börjar med budgeten."
    });
  });

  it("keeps the file a line belongs to, and reads an end before the start as the start", () => {
    expect(
      parseSegments([
        { segment_index: 3, file_index: 1, start: 5, end: 4, speaker: "", text: "Kort." }
      ])
    ).toEqual([{ index: 3, fileIndex: 1, start: 5, end: 5, speaker: null, text: "Kort." }]);
  });
});

describe("shownSegments", () => {
  const segments = parseSegments(raw);

  it("applies text corrections, whole-line speaker edits and names", () => {
    const shown = shownSegments(
      segments,
      corrections({
        occurrences: [
          {
            segment_index: 1,
            char_start: 20,
            char_end: 28,
            original: "budgeten",
            corrected: "budget"
          },
          { segment_index: 1, char_start: 0, char_end: 4, original: "Tack", corrected: "Tackar" }
        ],
        speaker_edits: [
          { segment_index: 2, original_speaker: "SPEAKER_00", speaker: "SPEAKER_01" }
        ],
        speaker_names: { SPEAKER_00: "Anna", SPEAKER_01: " " }
      })
    );
    expect(shown[1]?.text).toBe("Tackar, vi börjar med budget.");
    expect(shown[0]).toMatchObject({ label: "SPEAKER_00", name: "Anna" });
    expect(shown[2]).toMatchObject({ label: "SPEAKER_01", name: null });
    expect(speakerLabels(shown)).toEqual(["SPEAKER_00", "SPEAKER_01"]);
  });

  it("applies an occurrence only where its original text still stands", () => {
    const shown = shownSegments(
      segments,
      corrections({
        occurrences: [
          { segment_index: 2, char_start: 0, char_end: 3, original: "Dålig", corrected: "Utmärkt" }
        ]
      })
    );
    expect(shown[2]?.text).toBe("Bra.");
  });
});

describe("speakerNamesRequest", () => {
  it("sets the names and keeps every other saved correction", () => {
    const saved = corrections({
      occurrences: [
        { segment_index: 2, char_start: 0, char_end: 3, original: "Bra", corrected: "Utmärkt" }
      ]
    });
    expect(speakerNamesRequest(saved, "hash-2", { SPEAKER_00: " Anna ", SPEAKER_01: "" })).toEqual({
      expected_revision: 2,
      segments_hash: "hash-1",
      occurrences: saved.occurrences,
      speaker_edits: [],
      speaker_names: { SPEAKER_00: "Anna", SPEAKER_01: null },
      schema_version: 3
    });
  });

  it("starts the first set from the source's hash", () => {
    expect(speakerNamesRequest(null, "hash-2", { SPEAKER_00: "Anna" })).toMatchObject({
      expected_revision: null,
      segments_hash: "hash-2"
    });
  });
});

describe("clockTime", () => {
  it("writes minutes and seconds, and hours past the hour", () => {
    expect(clockTime(65.4)).toBe("1:05");
    expect(clockTime(3725)).toBe("1:02:05");
  });
});
