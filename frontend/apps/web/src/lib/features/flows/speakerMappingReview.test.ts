import { describe, expect, it } from "vitest";

import {
  buildEditedMapping,
  buildSpeakerRows,
  effectiveSpeakerNames,
  getSpeakerMappingInferNames,
  getSpeakerMappingParticipants,
  isSpeakerMappingCheckpoint
} from "./speakerMappingReview";

const payload = {
  text: "[00:00:00 - 00:00:04] Anna: Hej.",
  structured: {
    speakers: [
      { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "presenterar sig" },
      { label: "SPEAKER_01", name: null, confidence: "weird" }
    ]
  },
  speaker_mapping: {
    participants: ["Anna", "Bo", ""],
    inventory: [
      { label: "SPEAKER_00", line_count: 3, samples: ["Hej.", "Vi börjar."] },
      { label: "SPEAKER_01", line_count: 1, samples: [] }
    ]
  }
};

describe("speaker mapping review", () => {
  it("recognises the checkpoint by its payload extension", () => {
    expect(isSpeakerMappingCheckpoint(payload)).toBe(true);
    expect(isSpeakerMappingCheckpoint({ text: "x", structured: {} })).toBe(false);
    expect(isSpeakerMappingCheckpoint(null)).toBe(false);
  });

  it("reads whether names may come from the conversation, off by default", () => {
    expect(getSpeakerMappingInferNames(payload)).toBe(false);
    expect(
      getSpeakerMappingInferNames({
        ...payload,
        speaker_mapping: { ...payload.speaker_mapping, infer_names: true }
      })
    ).toBe(true);
    expect(getSpeakerMappingInferNames(null)).toBe(false);
  });

  it("builds one row per inventory speaker with the proposal merged in", () => {
    expect(getSpeakerMappingParticipants(payload)).toEqual(["Anna", "Bo"]);
    expect(buildSpeakerRows(payload)).toEqual([
      {
        label: "SPEAKER_00",
        lineCount: 3,
        samples: ["Hej.", "Vi börjar."],
        name: "Anna",
        confidence: "high",
        evidence: "presenterar sig"
      },
      {
        label: "SPEAKER_01",
        lineCount: 1,
        samples: [],
        name: null,
        confidence: "low",
        evidence: ""
      }
    ]);
  });

  it("serialises rows to the mapping the API accepts", () => {
    const rows = buildSpeakerRows(payload);
    rows[1] = { ...rows[1], name: "  Okänd gäst " };
    expect(buildEditedMapping(rows)).toEqual({
      speakers: [
        { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "presenterar sig" },
        { label: "SPEAKER_01", name: "Okänd gäst", confidence: "low", evidence: "" }
      ]
    });
  });
});

describe("effective speaker names", () => {
  const base = { SPEAKER_00: "Anna", SPEAKER_01: "Bo" };

  // The same table as the backend's effective_speaker_names.
  it.each([
    // An absent label inherits the step's name.
    [{}, { SPEAKER_00: "Anna", SPEAKER_01: "Bo" }],
    // A string overrides it.
    [{ SPEAKER_00: "Anna Berg" }, { SPEAKER_00: "Anna Berg", SPEAKER_01: "Bo" }],
    // Null removes it: explicitly no name.
    [{ SPEAKER_01: null }, { SPEAKER_00: "Anna" }],
    // A label the step left unnamed is named; null on it changes nothing.
    [
      { SPEAKER_02: "Cecilia", SPEAKER_03: null },
      { SPEAKER_00: "Anna", SPEAKER_01: "Bo", SPEAKER_02: "Cecilia" }
    ]
  ] as [Record<string, string | null>, Record<string, string>][])(
    "puts a person's names over the step's (%j)",
    (overrides, expected) => {
      expect(effectiveSpeakerNames(base, overrides)).toEqual(expected);
      expect(base).toEqual({ SPEAKER_00: "Anna", SPEAKER_01: "Bo" });
    }
  );
});
