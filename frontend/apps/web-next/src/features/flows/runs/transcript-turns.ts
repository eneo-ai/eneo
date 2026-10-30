import type { ShownSegment } from "./transcript";
import {
  withLineText,
  withSpeaker,
  type CorrectionSet,
  type SpeakerDecision
} from "./transcript-corrections";

/**
 * Speaker turns: consecutive parts of the shown lines that the same speaker
 * said, read as one paragraph instead of the transcription's fragments.
 * The line stays the unit underneath: every part keeps its line and where
 * it stands in the line's text, so playing, selecting and reassigning work
 * on turns as on lines. A new file, or a part whose speaker is marked
 * unsure, always starts a turn of its own.
 *
 * A turn is edited as one text; the edit is saved as the corrections of the
 * lines it changes. Its speaker is given, or reset, part by part. Pure.
 */

export type TurnMarker = "unresolved" | "unsure";

export type TurnPart = {
  /** The line's place among the shown lines. */
  position: number;
  segmentIndex: number;
  text: string;
  /** Where the part starts in the line's corrected text. */
  shownStart: number;
  /** The part's span of the line's raw text, which a speaker edit anchors to. */
  rawStart: number;
  rawEnd: number;
  /** A speaker edit gave the part its speaker. */
  overridden: boolean;
};

export type Turn = {
  speaker: string | null;
  name: string | null;
  marker: TurnMarker | null;
  fileIndex: number;
  /** Seconds into its file where the turn's first line starts. */
  start: number;
  parts: TurnPart[];
};

function markerOf(segment: ShownSegment, part: ShownSegment["parts"][number]): TurnMarker | null {
  if (part.decision === "unresolved") return "unresolved";
  return segment.parts.length === 1 && segment.unsure ? "unsure" : null;
}

export function transcriptTurns(shown: readonly ShownSegment[]): Turn[] {
  const turns: Turn[] = [];
  shown.forEach((segment, position) => {
    let shownStart = 0;
    for (const part of segment.parts) {
      const start = shownStart;
      shownStart += part.text.length;
      if (!part.text.trim()) continue;
      const marker = markerOf(segment, part);
      const last = turns.at(-1);
      const piece: TurnPart = {
        position,
        segmentIndex: segment.index,
        text: part.text,
        shownStart: start,
        rawStart: part.rawStart,
        rawEnd: part.rawEnd,
        overridden: part.overridden
      };
      if (
        last &&
        last.speaker === part.speaker &&
        last.fileIndex === segment.fileIndex &&
        last.marker === null &&
        marker === null
      ) {
        last.parts.push(piece);
        continue;
      }
      turns.push({
        speaker: part.speaker,
        name: part.name,
        marker,
        fileIndex: segment.fileIndex,
        start: segment.start,
        parts: [piece]
      });
    }
  });
  return turns;
}

/** The line a turn part belongs to, as the edits need it. */
type TurnLine = Pick<ShownSegment, "index" | "raw" | "text" | "speaker">;

/** Two parts read as one text get a space between them where neither has one at the seam. */
function separator(previous: string | undefined, next: string): string {
  return previous !== undefined && !/\s$/.test(previous) && !/^\s/.test(next) ? " " : "";
}

function joined(turn: Pick<Turn, "parts">): { text: string; starts: number[]; seps: string[] } {
  let text = "";
  const starts: number[] = [];
  const seps: string[] = [];
  turn.parts.forEach((part, at) => {
    const sep = separator(turn.parts[at - 1]?.text, part.text);
    if (at > 0) seps.push(sep);
    text += sep;
    starts.push(text.length);
    text += part.text;
  });
  return { text, starts, seps };
}

/** The text a turn is edited as: its parts, with a space between them where the turn shows one. */
export function turnText(turn: Pick<Turn, "parts">): string {
  return joined(turn).text;
}

/**
 * The corrected texts of the lines an edit of the turn's text changes. The
 * edit is one changed window (the common start and end trimmed, then
 * widened to whole words, so a word is never split between two lines):
 * parts before and after it keep their text, the first part it touches
 * takes the new text, and parts wholly inside it lose theirs. Text typed at
 * the end of a part joins that part; after the space between two parts, the
 * next one.
 */
export function turnLineTexts(
  turn: Pick<Turn, "parts">,
  edited: string,
  lineText: (segmentIndex: number) => string | undefined
): Map<number, string> {
  const { text: original, starts, seps } = joined(turn);
  const result = new Map<number, string>();
  if (original === edited) return result;
  let windowStart = 0;
  const shortest = Math.min(original.length, edited.length);
  while (windowStart < shortest && original[windowStart] === edited[windowStart]) windowStart += 1;
  let windowEnd = original.length;
  let editedEnd = edited.length;
  while (
    windowEnd > windowStart &&
    editedEnd > windowStart &&
    original[windowEnd - 1] === edited[editedEnd - 1]
  ) {
    windowEnd -= 1;
    editedEnd -= 1;
  }
  while (windowStart > 0 && !/\s/.test(original[windowStart - 1]!)) windowStart -= 1;
  while (windowEnd < original.length && !/\s/.test(original[windowEnd]!)) {
    windowEnd += 1;
    editedEnd += 1;
  }
  const shift = editedEnd - windowEnd;
  const mapped = (offset: number) =>
    offset <= windowStart ? offset : offset >= windowEnd ? offset + shift : editedEnd;

  const texts: string[] = [];
  let previousEnd = 0;
  turn.parts.forEach((part, at) => {
    const last = at === turn.parts.length - 1;
    const start = at === 0 ? 0 : Math.max(mapped(starts[at]!), previousEnd);
    const end = last ? edited.length : Math.max(mapped(starts[at]! + part.text.length), start);
    if (at > 0) {
      const gap = edited.slice(previousEnd, start);
      const sep = seps[at - 1]!;
      if (gap !== sep) texts[at - 1] += sep && gap.endsWith(sep) ? gap.slice(0, -sep.length) : gap;
    }
    texts.push(edited.slice(start, end));
    previousEnd = end;
  });

  // Each changed part replaces its slice of its line's corrected text, last first.
  const changes = turn.parts
    .map((part, at) => ({ part, text: texts[at]! }))
    .filter(({ part, text }) => text !== part.text)
    .sort((a, b) => b.part.shownStart - a.part.shownStart);
  for (const { part, text } of changes) {
    const line = result.get(part.segmentIndex) ?? lineText(part.segmentIndex);
    if (line === undefined) continue;
    result.set(
      part.segmentIndex,
      line.slice(0, part.shownStart) + text + line.slice(part.shownStart + part.text.length)
    );
  }
  return result;
}

/** The set with a turn's text edited, and the lines' new corrected texts. */
export function withTurnText(
  set: CorrectionSet,
  turn: Pick<Turn, "parts">,
  edited: string,
  lines: ReadonlyMap<number, TurnLine>
): { next: CorrectionSet; texts: Map<number, string> } {
  const texts = turnLineTexts(turn, edited, (index) => lines.get(index)?.text);
  let next = set;
  for (const [index, text] of texts) {
    const line = lines.get(index);
    if (line) next = withLineText(next, { index, text: line.raw }, text);
  }
  return { next, texts };
}

/**
 * The set with parts (of a turn, or of a line) given to a speaker, or reset
 * to their line's own speaker. A part that is its whole line is reassigned
 * as the line.
 */
export function withPartsSpeaker(
  set: CorrectionSet,
  parts: readonly Pick<TurnPart, "segmentIndex" | "rawStart" | "rawEnd" | "overridden">[],
  lines: ReadonlyMap<number, TurnLine>,
  change: { speaker: string | null; decision: SpeakerDecision } | "reset"
): CorrectionSet {
  let next = set;
  for (const part of parts) {
    const line = lines.get(part.segmentIndex);
    if (!line || (change === "reset" && !part.overridden)) continue;
    const whole = part.rawStart === 0 && part.rawEnd === line.raw.length;
    next = withSpeaker(
      next,
      { index: line.index, text: line.raw, speaker: line.speaker },
      whole ? null : { start: part.rawStart, end: part.rawEnd },
      change
    );
  }
  return next;
}
