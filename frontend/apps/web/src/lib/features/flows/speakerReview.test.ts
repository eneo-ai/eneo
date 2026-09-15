import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  effectiveSpeaker,
  PROVISIONAL_SPEAKER,
  UNRESOLVED_SPEAKER,
  renderReviewedTranscript
} from "./speakerReview";
import { segmentsFromMetadata, attachWords } from "./transcriptSegments";
import { applySpeakerEditOverlay } from "./transcriptRuns";
import { computeTurns } from "./transcriptTurns";

const cases = JSON.parse(
  readFileSync(
    new URL("../../../../../../../backend/tests/fixtures/speaker_review.json", import.meta.url),
    "utf8"
  )
).cases;

describe("shared Vemsa speaker-review contract", () => {
  for (const fixture of cases) {
    it(`loads, reviews, reloads and exports ${fixture.name}`, () => {
      const wire = fixture.result;
      const metadata = {
        segments: wire.segments.map((segment: Record<string, unknown>) => ({
          ...segment,
          file_index: 0
        })),
        segments_hash: "a".repeat(64),
        speaker_review: wire.speaker_review
          ? { files: [{ ...wire.speaker_review, file_index: 0 }] }
          : null
      };
      const parsed = segmentsFromMetadata(metadata)!;
      const segments = attachWords(parsed, {
        segments: wire.segments.map((segment: { words: unknown[] }, index: number) => ({
          segment_index: index,
          words: segment.words
        }))
      });
      expect(renderReviewedTranscript(segments, [], [])).toBe(wire.text);
      for (const segment of segments) {
        const edits = applySpeakerEditOverlay(
          [],
          [
            {
              segment_index: segment.index,
              char_start: null,
              char_end: null,
              speaker: null,
              decision: "unresolved"
            }
          ],
          segments
        );
        const reloaded = JSON.parse(JSON.stringify(edits));
        const turns = computeTurns(segments, [], reloaded);
        expect(turns.some((turn) => turn.speaker === UNRESOLVED_SPEAKER)).toBe(true);
        expect(renderReviewedTranscript(segments, [], reloaded)).toContain(
          `[Talare går inte att avgöra]: ${segment.text}`
        );
        const confirmed = applySpeakerEditOverlay(
          reloaded,
          [
            {
              segment_index: segment.index,
              char_start: null,
              char_end: null,
              speaker: segment.speaker ?? "SPEAKER_00"
            }
          ],
          segments
        );
        expect(confirmed.find((edit) => edit.segment_index === segment.index)?.decision).toBe(
          "confirmed"
        );
        const undone = applySpeakerEditOverlay(
          confirmed,
          [
            {
              segment_index: segment.index,
              char_start: null,
              char_end: null,
              speaker: segment.speaker,
              reset: true
            }
          ],
          segments
        );
        expect(renderReviewedTranscript(segments, [], undone)).toBe(wire.text);
      }
    });
  }
});

it("keeps a same-label confirmation bounded inside provisional words", () => {
  const segments = [
    {
      index: 0,
      fileIndex: 0,
      start: 0,
      end: 3,
      text: "Hej där alla",
      speaker: "SPEAKER_00",
      speakerAttribution: "provisional"
    }
  ];
  const edits = applySpeakerEditOverlay(
    [],
    [
      {
        segment_index: 0,
        char_start: 4,
        char_end: 7,
        speaker: "SPEAKER_00"
      }
    ],
    segments
  );
  expect(computeTurns(segments, [], edits).map((turn) => turn.speaker)).toEqual([
    PROVISIONAL_SPEAKER,
    "SPEAKER_00",
    PROVISIONAL_SPEAKER
  ]);
  expect(renderReviewedTranscript(segments, [], edits, { SPEAKER_00: "Anna" })).toBe(
    "[00:00:00 - 00:00:03] [Överlappande tal – osäker talare]: Hej\n" +
      "[00:00:00 - 00:00:03] Anna: där\n" +
      "[00:00:00 - 00:00:03] [Överlappande tal – osäker talare]: alla"
  );
});

it("does not mistake a model assignment for human confirmation", () => {
  const segment = {
    index: 0,
    fileIndex: 0,
    start: 0,
    end: 1,
    text: "Hej",
    speaker: "SPEAKER_00",
    speakerAttribution: "assigned"
  };
  expect(computeTurns([segment], [], [])[0].parts[0].overridden).toBe(false);
  expect(effectiveSpeaker({ ...segment, speakerAttribution: "provisional" })).toBe(
    PROVISIONAL_SPEAKER
  );
});
