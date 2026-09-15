import { describe, it, expect } from "vitest";
import {
  reviewFragments,
  reviewParagraphs,
  wholePassage,
  assignSelection,
  pendingSuggestions,
  confirmSuggestions,
  sharedSuggestion,
  replaceReviewText,
  highlightedReviewWords,
  type ReviewDraft
} from "./transcriptReviewEditor";
import type { TranscriptSegment } from "./transcriptSegments";
const raw: TranscriptSegment[] = [
  {
    index: 0,
    fileIndex: 0,
    start: 0,
    end: 4,
    speaker: "SPEAKER_00",
    speakerAttribution: "provisional",
    text: "🙂 Hej. Fortsätt."
  },
  {
    index: 1,
    fileIndex: 0,
    start: 4,
    end: 8,
    speaker: "SPEAKER_01",
    speakerAttribution: "provisional",
    text: "Ja tack."
  }
];
const empty: ReviewDraft = { occurrences: [], speakerEdits: [] };
describe("transcript-first review", () => {
  it("keeps uncertainty partitions inside a paragraph without changing sources", () => {
    const draft = assignSelection(
      empty,
      raw,
      [{ segmentIndex: 0, start: 3, end: 7 }],
      "SPEAKER_01"
    );
    const shown = reviewFragments(raw, draft);
    expect(reviewParagraphs(shown)[0]).toHaveLength(3);
    expect(
      reviewParagraphs(shown)[0]
        .map((f) => f.text)
        .join("")
    ).toBe(raw[0].text);
    expect(raw[0].speaker).toBe("SPEAKER_00");
  });
  it("bulk confirmation preserves unresolved decisions and corrections; each proposal uses its own speaker", () => {
    const prior = assignSelection(
      {
        ...empty,
        occurrences: [
          { segment_index: 0, char_start: 5, char_end: 6, original: "j", corrected: "j!" }
        ]
      },
      raw,
      [{ segmentIndex: 0, start: 3, end: 7 }],
      null
    );
    const shown = reviewFragments(raw, prior);
    const next = confirmSuggestions(prior, raw, pendingSuggestions(shown));
    expect(next.occurrences).toEqual(prior.occurrences);
    expect(next.speakerEdits.some((e) => e.decision === "unresolved")).toBe(true);
    expect(next.speakerEdits.some((e) => e.segment_index === 1 && e.speaker === "SPEAKER_01")).toBe(
      true
    );
    expect(pendingSuggestions(reviewFragments(raw, next))).toHaveLength(0);
  });
  it("whole passage selection includes punctuation and whitespace", () => {
    expect(wholePassage(reviewFragments(raw, empty)[0])).toEqual([
      { segmentIndex: 0, start: 0, end: raw[0].text.length }
    ]);
  });
  it("mixed suggestions and an explicit unresolved decision cannot quick-confirm one speaker", () => {
    expect(sharedSuggestion(reviewFragments(raw, empty))).toBeNull();
    const next = assignSelection(empty, raw, wholePassage(reviewFragments(raw, empty)[0]), null);
    expect(sharedSuggestion(reviewFragments(raw, next).slice(0, 1))).toBeNull();
  });
  it("resets only selected words and leaves neighbouring decisions", () => {
    const all = assignSelection(
      empty,
      raw,
      [{ segmentIndex: 0, start: 0, end: raw[0].text.length }],
      "SPEAKER_01"
    );
    const next = assignSelection(all, raw, [{ segmentIndex: 0, start: 3, end: 7 }], null, true);
    expect(next.speakerEdits).toHaveLength(2);
    expect(next.speakerEdits.every((e) => e.char_end! <= 3 || e.char_start! >= 7)).toBe(true);
  });
  it("inserts punctuation inside its speaker partition and preserves caret across subsequent typing", () => {
    const base = assignSelection(empty, raw, [{ segmentIndex: 0, start: 3, end: 7 }], null);
    const shown = reviewFragments(raw, base);
    const result = replaceReviewText(base, shown, [{ index: 1, start: 3, end: 3 }], "!");
    expect(result.draft.occurrences[0]).toMatchObject({
      char_start: 6,
      char_end: 7,
      original: ".",
      corrected: "!."
    });
    expect(result.caret).toEqual({ segmentIndex: 0, offset: 7 });
    const nextShown = reviewFragments(raw, result.draft);
    const next = replaceReviewText(result.draft, nextShown, [{ index: 1, start: 4, end: 4 }], "?");
    expect(nextShown[1].text).toBe("Hej!.");
    expect(reviewFragments(raw, next.draft)[1].text).toBe("Hej!?.");
    expect(next.draft.speakerEdits).toEqual(base.speakerEdits);
  });
  it("keeps complete emoji insertion anchors", () => {
    const result = replaceReviewText(
      empty,
      reviewFragments(raw, empty),
      [{ index: 0, start: 0, end: 0 }],
      "!"
    );
    expect(result.draft.occurrences[0]).toMatchObject({
      original: "🙂",
      char_start: 0,
      char_end: 2,
      corrected: "!🙂"
    });
  });
  it("invalidates touched words and preserves simultaneous words and silence highlights", () => {
    const segments = [
      {
        ...raw[0],
        words: [
          {
            word: "Hej",
            start: 1,
            end: 2,
            charStart: 3,
            charEnd: 6,
            probability: 1,
            uncertain: false
          },
          {
            word: "Fortsätt",
            start: 3,
            end: 4,
            charStart: 8,
            charEnd: 16,
            probability: 1,
            uncertain: false
          }
        ]
      },
      {
        ...raw[1],
        words: [
          {
            word: "Ja",
            start: 1,
            end: 2,
            charStart: 0,
            charEnd: 2,
            probability: 1,
            uncertain: false
          }
        ]
      }
    ];
    const shown = reviewFragments(segments, empty);
    expect(highlightedReviewWords(shown, 0, 1.5).size).toBe(2);
    expect(highlightedReviewWords(shown, 0, 2.5).size).toBe(2);
    expect(highlightedReviewWords(shown, 1, 2.5).size).toBe(0);
    expect(highlightedReviewWords(shown, 0, 0).size).toBe(0);
    const changed = replaceReviewText(empty, shown, [{ index: 0, start: 3, end: 6 }], "Hallå");
    expect(reviewFragments(segments, changed.draft)[0].words.map((w) => w.word)).toEqual([
      "Fortsätt"
    ]);
  });
  it("does not merge unrelated unknown speakers or cross file boundaries", () => {
    const unknown = raw.map((s) => ({ ...s, speaker: null }));
    expect(reviewParagraphs(reviewFragments(unknown, empty))).toHaveLength(2);
    expect(
      reviewParagraphs(
        reviewFragments(
          raw.map((s, i) => ({ ...s, fileIndex: i, speaker: "SPEAKER_00" })),
          empty
        )
      )
    ).toHaveLength(2);
  });
});

it("joins a continuation from the last settled speaker without merging the source anchors", () => {
  const segments = [
    { ...raw[0], text: "Anna börjar. Bo fortsätter.", speakerAttribution: "assigned" },
    { ...raw[1], text: "än vad du har gjort.", speakerAttribution: "assigned" }
  ];
  const draft = assignSelection(
    empty,
    segments,
    [{ segmentIndex: 0, start: 13, end: segments[0].text.length }],
    "SPEAKER_01"
  );
  const paragraphs = reviewParagraphs(reviewFragments(segments, draft));
  expect(paragraphs).toHaveLength(1);
  expect(paragraphs[0].map((f) => f.source.index)).toEqual([0, 0, 1]);
});
