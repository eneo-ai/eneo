/** Transcript-first editing uses UTF-16 locally; the controller converts wire anchors. */
import { diffLineEdit, type CorrectionOccurrence } from "./transcriptCorrections";
import {
  applySpeakerEditOverlay,
  buildOffsetMap,
  computeSegmentDetails,
  type SpeakerEdit
} from "./transcriptRuns";
import type { TranscriptSegment, TranscriptWord } from "./transcriptSegments";

export type ReviewDraft = { occurrences: CorrectionOccurrence[]; speakerEdits: SpeakerEdit[] };
export type ReviewSelection = { segmentIndex: number; start: number; end: number };
export type DisplayRange = { index: number; start: number; end: number };
export type ReviewFragment = {
  index: number;
  source: TranscriptSegment;
  rawStart: number;
  rawEnd: number;
  displayStart: number;
  text: string;
  speaker: string | null;
  decision?: "confirmed" | "unresolved";
  pending: boolean;
  words: TranscriptWord[];
};

export function reviewFragments(
  raw: readonly TranscriptSegment[],
  draft: ReviewDraft
): ReviewFragment[] {
  const details = computeSegmentDetails(raw, draft.occurrences, draft.speakerEdits);
  return raw
    .flatMap((source) => {
      const occurrences = draft.occurrences.filter((o) => o.segment_index === source.index);
      const map = buildOffsetMap(source.text, occurrences);
      return (details.get(source.index)?.runs ?? []).map((run) => ({
        index: 0,
        source,
        rawStart: run.rawStart,
        rawEnd: run.rawEnd,
        displayStart: run.displayStart,
        text: run.text,
        speaker: run.overridden ? run.speaker : source.speaker,
        decision: run.overridden ? (run.decision ?? "confirmed") : undefined,
        pending:
          !run.overridden &&
          (source.speakerAttribution === "provisional" ||
            source.speakerAttribution === "unassigned" ||
            source.speaker === null),
        words: (source.words ?? [])
          .filter(
            (w) =>
              w.charStart >= run.rawStart &&
              w.charEnd <= run.rawEnd &&
              !occurrences.some((o) => w.charStart < o.char_end && w.charEnd > o.char_start)
          )
          .map((w) => ({
            ...w,
            charStart: map.rawToDisplay(w.charStart) - run.displayStart,
            charEnd: map.rawToDisplay(w.charEnd) - run.displayStart
          }))
      }));
    })
    .map((fragment, index) => ({ ...fragment, index }));
}

export function reviewParagraphs(shown: readonly ReviewFragment[]): ReviewFragment[][] {
  const groups: ReviewFragment[][] = [];
  for (const fragment of shown) {
    const group = groups.at(-1);
    const previous = group?.at(-1);
    const lastSpeech = group?.findLast((f) => f.text.trim());
    const sameSource = previous?.source.index === fragment.source.index;
    const continuation =
      lastSpeech?.speaker &&
      lastSpeech.speaker === fragment.speaker &&
      !lastSpeech.pending &&
      !fragment.pending &&
      lastSpeech.decision !== "unresolved" &&
      fragment.decision !== "unresolved";
    if (
      !previous ||
      previous.source.fileIndex !== fragment.source.fileIndex ||
      (!sameSource &&
        (((!fragment.source.speaker || previous.source.speaker !== fragment.source.speaker) &&
          !continuation) ||
          fragment.source.start - previous.source.end > 3 ||
          group!.reduce((n, f) => n + f.text.length, 0) > 650))
    ) {
      groups.push([fragment]);
    } else group!.push(fragment);
  }
  return groups.filter((group) => group.some((f) => f.text.trim()));
}

export function wholePassage(fragment: ReviewFragment): ReviewSelection[] {
  return fragment.text.trim()
    ? [{ segmentIndex: fragment.source.index, start: fragment.rawStart, end: fragment.rawEnd }]
    : [];
}

export function selectionBounds(
  selection: ReviewSelection[],
  fragment: ReviewFragment,
  draft: ReviewDraft
) {
  const map = buildOffsetMap(
    fragment.source.text,
    draft.occurrences.filter((o) => o.segment_index === fragment.source.index)
  );
  return selection
    .filter((s) => s.segmentIndex === fragment.source.index)
    .map((s) => ({
      start: Math.max(0, map.rawToDisplay(s.start) - fragment.displayStart),
      end: Math.min(fragment.text.length, map.rawToDisplay(s.end) - fragment.displayStart)
    }))
    .filter((s) => s.end > s.start);
}

export function anchorSelection(
  ranges: DisplayRange[],
  shown: ReviewFragment[],
  draft: ReviewDraft
): ReviewSelection[] {
  return ranges.flatMap((range) => {
    const f = shown[range.index];
    const words = [...f.text.matchAll(/\S+/gu)].filter(
      (m) => m.index! < range.end && m.index! + m[0].length > range.start
    );
    if (!words.length) return [];
    const map = buildOffsetMap(
      f.source.text,
      draft.occurrences.filter((o) => o.segment_index === f.source.index)
    );
    return [
      {
        segmentIndex: f.source.index,
        start: map.displayToRaw(f.displayStart + words[0].index!, "start"),
        end: map.displayToRaw(
          f.displayStart + words.at(-1)!.index! + words.at(-1)![0].length,
          "end"
        )
      }
    ];
  });
}

export function assignSelection(
  draft: ReviewDraft,
  raw: readonly TranscriptSegment[],
  selection: ReviewSelection[],
  speaker: string | null,
  reset = false
): ReviewDraft {
  return {
    ...draft,
    speakerEdits: applySpeakerEditOverlay(
      draft.speakerEdits,
      selection.map((s) => ({
        segment_index: s.segmentIndex,
        char_start: s.start,
        char_end: s.end,
        speaker,
        decision: speaker === null ? "unresolved" : "confirmed",
        reset
      })),
      raw,
      true
    )
  };
}

export function pendingSuggestions(shown: ReviewFragment[], selection?: ReviewSelection[]) {
  return shown.flatMap((f) =>
    !f.pending || f.decision || !f.text.trim() || !f.source.speaker
      ? []
      : (selection
          ? selection
              .filter((s) => s.segmentIndex === f.source.index)
              .map((s) => ({
                segmentIndex: s.segmentIndex,
                start: Math.max(s.start, f.rawStart),
                end: Math.min(s.end, f.rawEnd)
              }))
              .filter((s) => s.end > s.start)
          : wholePassage(f)
        ).map((range) => ({ range, speaker: f.source.speaker! }))
  );
}

export function confirmSuggestions(
  draft: ReviewDraft,
  raw: readonly TranscriptSegment[],
  suggestions: ReturnType<typeof pendingSuggestions>
) {
  return suggestions.reduce((next, s) => assignSelection(next, raw, [s.range], s.speaker), draft);
}

export function sharedSuggestion(shown: ReviewFragment[]): string | null {
  const words = shown.filter((f) => f.text.trim());
  const speaker = words[0]?.source.speaker;
  return speaker &&
    words.every(
      (f) =>
        f.source.speaker === speaker &&
        (!f.decision || (f.decision === "confirmed" && f.speaker === speaker))
    )
    ? speaker
    : null;
}

/** Recompute each touched speaker partition independently, including insertion anchors. */
export function replaceReviewText(
  draft: ReviewDraft,
  shown: ReviewFragment[],
  ranges: DisplayRange[],
  text: string
) {
  if (!ranges.length) throw new Error("Placera markören i transkripttexten.");
  let next = { ...draft, occurrences: [...draft.occurrences] };
  const first = shown[ranges[0].index];
  const caret = {
    segmentIndex: first.source.index,
    offset: first.displayStart + ranges[0].start + text.length
  };
  for (const [i, range] of ranges.entries()) {
    const f = shown[range.index];
    if (!f || range.start < 0 || range.end < range.start || range.end > f.text.length)
      throw new Error("Markeringen behöver göras om.");
    const replacement =
      f.text.slice(0, range.start) + (i === 0 ? text : "") + f.text.slice(range.end);
    const occurrence = diffLineEdit(
      f.source.text.slice(f.rawStart, f.rawEnd),
      replacement
    ).occurrence;
    next = {
      ...next,
      occurrences: [
        ...next.occurrences.filter(
          (o) =>
            o.segment_index !== f.source.index ||
            o.char_end <= f.rawStart ||
            o.char_start >= f.rawEnd
        ),
        ...(occurrence
          ? [
              {
                ...occurrence,
                segment_index: f.source.index,
                char_start: occurrence.char_start + f.rawStart,
                char_end: occurrence.char_end + f.rawStart
              }
            ]
          : [])
      ].sort((a, b) => a.segment_index - b.segment_index || a.char_start - b.char_start)
    };
  }
  return { draft: next, caret };
}

/** Active overlapping words are simultaneous; gaps retain the last completed word. */
export function highlightedReviewWords(
  shown: ReviewFragment[],
  file: number,
  time: number
): Set<TranscriptWord> {
  const words = shown.filter((f) => f.source.fileIndex === file).flatMap((f) => f.words);
  const active = words.filter((w) => w.start <= time && time < w.end);
  if (active.length) return new Set(active);
  const lastEnd = Math.max(-1, ...words.filter((w) => w.end <= time).map((w) => w.end));
  return new Set(words.filter((w) => w.end === lastEnd));
}

export function reviewSelectionText(
  shown: ReviewFragment[],
  selection: ReviewSelection[],
  draft: ReviewDraft
) {
  let previous: number | null = null;
  let text = "";
  for (const f of shown) {
    const bounds = selectionBounds(selection, f, draft);
    if (!bounds.length) continue;
    if (previous !== null && previous !== f.source.index) text += " ";
    text += bounds.map((b) => f.text.slice(b.start, b.end)).join("");
    previous = f.source.index;
  }
  return text;
}
