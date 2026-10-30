import type { Schema } from "@/lib/api/models";
import type { TranscriptSegment } from "./transcript";

/**
 * Playing a transcript's audio: the word timings the transcription stored,
 * placed in each line's text, and which line and word play at a time. Pure;
 * the transcript player renders it.
 */

export type TranscriptWords = Schema<"FlowTranscriptWordsPublic">;

export type PlacedWord = {
  start: number;
  end: number;
  /** Where the word stands in the line's raw text; -1 when it could not be found. */
  charStart: number;
  charEnd: number;
  /** The aligner spread the word over its window instead of finding it in the audio. */
  uncertain: boolean;
};

// On the forced-alignment rung a probability of exactly 0 marks a word the
// aligner spread over its window instead of finding it in the audio.
const FORCED_ALIGNMENT = "forced";
const EDGE_PUNCTUATION = /^[\p{P}\p{S}]+|[\p{P}\p{S}]+$/gu;

/**
 * Places a line's words in its text by searching forward: a word usually
 * stands there as it is, else without the punctuation the aligner kept. A
 * word that cannot be found still plays, without a place to highlight.
 */
export function placeWords(
  text: string,
  words: readonly Schema<"TranscriptWordPublic">[],
  alignment: string | null
): PlacedWord[] {
  let cursor = 0;
  return words.map((word) => {
    const placed: PlacedWord = {
      start: word.start,
      end: Math.max(word.start, word.end),
      charStart: -1,
      charEnd: -1,
      uncertain: alignment === FORCED_ALIGNMENT && word.probability === 0
    };
    const candidates = [word.word, word.word.replace(EDGE_PUNCTUATION, "")].filter(Boolean);
    for (const candidate of candidates) {
      const at = text.indexOf(candidate, cursor);
      if (at < 0) continue;
      placed.charStart = at;
      placed.charEnd = at + candidate.length;
      cursor = placed.charEnd;
      break;
    }
    return placed;
  });
}

/**
 * The stored words per line, placed in its raw text. Words written for a
 * transcript that has changed since (`stale`, or another segments hash)
 * anchor to text that no longer exists: none are used.
 */
export function wordsByLine(
  segments: readonly TranscriptSegment[],
  payload: TranscriptWords | null | undefined,
  sourceHash: string
): ReadonlyMap<number, PlacedWord[]> {
  const placed = new Map<number, PlacedWord[]>();
  if (!payload || payload.stale) return placed;
  if (payload.segments_hash && sourceHash && payload.segments_hash !== sourceHash) return placed;
  const text = new Map(segments.map((segment) => [segment.index, segment.text]));
  for (const entry of payload.segments) {
    const raw = text.get(entry.segment_index);
    if (raw === undefined || entry.words.length === 0) continue;
    placed.set(entry.segment_index, placeWords(raw, entry.words, payload.alignment));
  }
  return placed;
}

/**
 * The line playing at `time` in file `fileIndex`, by position in `segments`
 * (in file and time order), or -1. Between two lines the earlier one stays
 * active, so the highlight does not flicker in pauses.
 */
export function activeLine(
  segments: readonly Pick<TranscriptSegment, "fileIndex" | "start">[],
  fileIndex: number,
  time: number
): number {
  let result = -1;
  let low = 0;
  let high = segments.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const segment = segments[mid]!;
    const before =
      segment.fileIndex < fileIndex || (segment.fileIndex === fileIndex && segment.start <= time);
    if (before) {
      if (segment.fileIndex === fileIndex) result = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return result;
}

/** The word playing at `time` among a line's words, or -1; between words the earlier stays. */
export function activeWord(words: readonly Pick<PlacedWord, "start">[], time: number): number {
  let result = -1;
  let low = 0;
  let high = words.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (words[mid]!.start <= time) {
      result = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return result;
}

/** A line's text cut at its placed words, for highlighting one: plain runs and word runs. */
export type TextRun = { text: string; word: number | null };

export function textRuns(text: string, words: readonly PlacedWord[]): TextRun[] {
  const runs: TextRun[] = [];
  let at = 0;
  words.forEach((word, index) => {
    if (word.charStart < at || word.charEnd > text.length) return;
    if (word.charStart > at) runs.push({ text: text.slice(at, word.charStart), word: null });
    runs.push({ text: text.slice(word.charStart, word.charEnd), word: index });
    at = word.charEnd;
  });
  if (at < text.length) runs.push({ text: text.slice(at), word: null });
  return runs;
}

function vttTime(seconds: number): string {
  const ms = Math.max(0, Math.round(seconds * 1000));
  const pad = (value: number, width = 2) => String(value).padStart(width, "0");
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.floor((ms % 3_600_000) / 60_000);
  const secs = Math.floor((ms % 60_000) / 1000);
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)}.${pad(ms % 1000, 3)}`;
}

/**
 * The lines of one audio file as WebVTT captions, with the speaker as the
 * cue's voice: the transcript as the audio element's own caption track.
 */
export function captionsFor(
  lines: readonly { fileIndex: number; start: number; end: number; text: string }[],
  fileIndex: number,
  speakerOf: (position: number) => string
): string {
  const cues = lines.flatMap((line, position) => {
    if (line.fileIndex !== fileIndex || !line.text.trim()) return [];
    const end = Math.max(line.end, line.start + 0.5);
    // A cue's text cannot hold a blank line or the "-->" arrow.
    const text = line.text.replace(/\s*\n\s*/g, " ").replace(/-->/g, "->");
    const voice = speakerOf(position).replace(/[<>&\n]/g, "");
    return [`${vttTime(line.start)} --> ${vttTime(end)}\n<v ${voice}>${text}`];
  });
  return ["WEBVTT", ...cues].join("\n\n") + "\n";
}
