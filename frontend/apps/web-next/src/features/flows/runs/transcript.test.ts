import { describe, expect, it } from "vitest";
import { makeRunStep } from "./run-fixtures";
import {
  clockTime,
  parseSegments,
  reviewTranscriptTarget,
  shownSegments,
  shownSegmentsOf,
  speakerLabels,
  speakerNamesRequest,
  transcriptTargets,
  type ShownSegment,
  type TranscriptCorrections,
  type TranscriptSegment,
  type TranscriptSourceSegment
} from "./transcript";
import {
  applicableOccurrences,
  lineParts,
  type CorrectionSet,
  type Occurrence,
  type WireSpeakerEdit
} from "./transcript-corrections";

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

describe("reviewTranscriptTarget", () => {
  const steps = [
    makeRunStep(1, {
      step_id: "step-1",
      input_payload_json: { transcription: { file_ids: ["f1"], source: { attempt_no: 1 } } }
    }),
    makeRunStep(2, { step_id: "step-2" }),
    makeRunStep(3, { step_id: "step-3" })
  ];

  it("finds the transcript a review is about: its own step's, or the one before a speaker mapping", () => {
    expect(reviewTranscriptTarget({ step_id: "step-1", step_order: 1 }, false, steps)?.stepId).toBe(
      "step-1"
    );
    expect(reviewTranscriptTarget({ step_id: "step-2", step_order: 2 }, true, steps)?.stepId).toBe(
      "step-1"
    );
    expect(reviewTranscriptTarget({ step_id: "step-3", step_order: 3 }, false, steps)).toBeNull();
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

/** `shownSegmentsOf` as it was before it grouped the corrections by line: the reference. */
function referenceShownSegmentsOf(
  segments: readonly TranscriptSegment[],
  set: CorrectionSet
): ShownSegment[] {
  const nameOf = (label: string | null) => (label ? set.names[label]?.trim() || null : null);
  return segments.map((segment) => {
    const own = set.occurrences.filter((occurrence) => occurrence.segment_index === segment.index);
    const corrected = applicableOccurrences(segment.text, own).length > 0;
    const parts = lineParts(
      segment.text,
      segment.speaker,
      own,
      set.speakerEdits.filter((edit) => edit.segment_index === segment.index)
    ).map((part) => ({ ...part, name: nameOf(part.speaker) }));
    const single = parts.length === 1 ? parts[0]! : null;
    const label = single ? single.speaker : segment.speaker;
    return {
      ...segment,
      text: parts.map((part) => part.text).join(""),
      raw: segment.text,
      label,
      name: nameOf(label),
      corrected,
      parts,
      decision: single?.decision ?? null,
      unsure: Boolean(segment.provisional) && !parts.some((part) => part.overridden)
    };
  });
}

/** A small seeded generator, so a failing case can be run again. */
function random(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

const WORDS = ["Tack", "vi", "börjar", "med", "budgeten", "Anna", "säger", "nej", "ja", "bra"];
const SPEAKERS = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", null];

function randomCase(seed: number): { segments: TranscriptSegment[]; set: CorrectionSet } {
  const next = random(seed);
  const pick = <T>(items: readonly T[]): T => items[Math.floor(next() * items.length)]!;
  const count = 1 + Math.floor(next() * 12);
  const segments: TranscriptSegment[] = Array.from({ length: count }, (_, position) => {
    const text = Array.from({ length: 1 + Math.floor(next() * 6) }, () => pick(WORDS)).join(" ");
    return {
      // Now and then two lines share an index, or an index is skipped.
      index: next() < 0.1 && position > 0 ? position - 1 : position + (next() < 0.1 ? 1 : 0),
      fileIndex: 0,
      start: position * 3,
      end: position * 3 + 2,
      speaker: pick(SPEAKERS),
      text,
      ...(next() < 0.3 ? { provisional: true } : {})
    };
  });
  const span = (text: string) => {
    const start = Math.floor(next() * text.length);
    const end = Math.min(text.length, start + 1 + Math.floor(next() * 8));
    return { start, end };
  };
  const occurrences: Occurrence[] = Array.from({ length: Math.floor(next() * 20) }, () => {
    const line = pick(segments);
    const { start, end } = span(line.text);
    const stale = next() < 0.2;
    return {
      segment_index: next() < 0.1 ? 99 : line.index,
      char_start: start,
      char_end: end,
      original: stale ? "inte här" : line.text.slice(start, end),
      corrected: pick(WORDS)
    };
  });
  const speakerEdits: WireSpeakerEdit[] = Array.from({ length: Math.floor(next() * 15) }, () => {
    const line = pick(segments);
    const whole = next() < 0.5;
    const { start, end } = span(line.text);
    return {
      segment_index: line.index,
      original_speaker: line.speaker,
      speaker: pick(SPEAKERS),
      ...(next() < 0.5 ? { decision: pick(["confirmed", "unresolved"] as const) } : {}),
      ...(whole ? {} : { char_start: start, char_end: end, original: line.text.slice(start, end) })
    };
  });
  const names: Record<string, string | null> = {
    SPEAKER_00: pick(["Anna", " ", null]),
    SPEAKER_01: pick(["Bo", ""])
  };
  return { segments, set: { occurrences, speakerEdits, names } };
}

describe("shownSegmentsOf", () => {
  it("shows every line as the reference does, on many random transcripts and corrections", () => {
    for (let seed = 1; seed <= 400; seed += 1) {
      const { segments, set } = randomCase(seed);
      expect(shownSegmentsOf(segments, set), `seed ${seed}`).toEqual(
        referenceShownSegmentsOf(segments, set)
      );
    }
  });

  it("applies a line's corrections in the order they were made, and only to that line", () => {
    const lines = parseSegments([
      { segment_index: 0, file_index: 0, start: 0, end: 2, speaker: "SPEAKER_00", text: "ja ja" },
      { segment_index: 1, file_index: 0, start: 2, end: 4, speaker: "SPEAKER_00", text: "ja ja" }
    ]);
    const shown = shownSegmentsOf(lines, {
      occurrences: [
        { segment_index: 1, char_start: 3, char_end: 5, original: "ja", corrected: "nej" },
        { segment_index: 1, char_start: 0, char_end: 2, original: "ja", corrected: "Jo" },
        { segment_index: 7, char_start: 0, char_end: 2, original: "ja", corrected: "aldrig" }
      ],
      speakerEdits: [],
      names: {}
    });
    expect(shown.map((line) => [line.text, line.corrected])).toEqual([
      ["ja ja", false],
      ["Jo nej", true]
    ]);
  });

  it("gives part of one line to another speaker, named, and leaves an unsure line decided", () => {
    const lines = parseSegments([
      {
        segment_index: 0,
        file_index: 0,
        start: 0,
        end: 2,
        speaker: "SPEAKER_00",
        text: "Hej. Tack.",
        speaker_attribution: "provisional"
      },
      {
        segment_index: 1,
        file_index: 0,
        start: 2,
        end: 4,
        speaker: "SPEAKER_00",
        text: "Bra.",
        speaker_attribution: "provisional"
      }
    ]);
    const shown = shownSegmentsOf(lines, {
      occurrences: [],
      speakerEdits: [
        {
          segment_index: 0,
          original_speaker: "SPEAKER_00",
          speaker: "SPEAKER_01",
          char_start: 5,
          char_end: 10,
          original: "Tack."
        }
      ],
      names: { SPEAKER_01: "Bo" }
    });
    expect(shown[0]!.parts.map((part) => [part.speaker, part.name, part.text.trim()])).toEqual([
      ["SPEAKER_00", null, "Hej."],
      ["SPEAKER_01", "Bo", "Tack."]
    ]);
    expect(shown[0]!.unsure).toBe(false);
    expect(shown[1]).toMatchObject({
      label: "SPEAKER_00",
      unsure: true,
      parts: [{ text: "Bra." }]
    });
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
