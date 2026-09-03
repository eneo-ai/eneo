/**
 * Structured view of a diarized transcript for a reader that plays the audio
 * alongside it: one segment per spoken line, placed in time.
 *
 * The transcription step stores segments in its metadata when the service
 * produced them; older runs (or oversized transcripts) only have the rendered
 * `[HH:MM:SS - HH:MM:SS] SPEAKER_00: text` lines, which parse to the same
 * shape at one-second precision.
 */
export type TranscriptSegment = {
  /** Stable position in the transcript; the anchor a future editor keys on. */
  index: number;
  /** Which audio file (in upload order) the timestamps belong to. */
  fileIndex: number;
  /** Seconds from the start of that file. */
  start: number;
  end: number;
  /** Diarization label (`SPEAKER_00`) or, in a renamed transcript, a name. */
  speaker: string | null;
  text: string;
  /** Timed words inside the line, when the service produced them. */
  words?: TranscriptWord[];
};

/** One timed word of a segment, located in the segment's RAW text. */
export type TranscriptWord = {
  word: string;
  /** Seconds from the start of the segment's file. */
  start: number;
  end: number;
  probability: number | null;
  /** Raw-text span within the segment, or -1/-1 when the word was not located. */
  charStart: number;
  charEnd: number;
  /** The aligner interpolated this word's time instead of finding it in the audio. */
  uncertain: boolean;
};

/** Wire shape of the transcript-words endpoint (matches the backend API). */
export type TranscriptWordsPayload = {
  alignment?: string | null;
  stale?: boolean;
  segments: { segment_index: number; words: TranscriptWirePayloadWord[] }[];
};

type TranscriptWirePayloadWord = {
  word: string;
  start: number;
  end: number;
  probability?: number | null;
};

// On the forced-alignment rung a probability of exactly 0 marks a word the
// aligner spread over its window instead of finding it in the audio.
const FORCED_ALIGNMENT = "forced";

const EDGE_PUNCTUATION_RE = /^[\p{P}\p{S}]+|[\p{P}\p{S}]+$/gu;

/**
 * Place `words` in `text` by sequential search. Tokens usually appear
 * verbatim; a token the aligner stripped of punctuation is retried bare.
 * A word that still cannot be found is kept (it still counts, still plays)
 * but marked unlocated so no text range is highlighted for it.
 */
export function locateWords(
  text: string,
  words: readonly TranscriptWirePayloadWord[],
  alignment: string | null | undefined
): TranscriptWord[] {
  let cursor = 0;
  return words.map((word) => {
    const probability = finite(word.probability) ?? null;
    const located: TranscriptWord = {
      word: word.word,
      start: word.start,
      end: Math.max(word.start, word.end),
      probability,
      charStart: -1,
      charEnd: -1,
      uncertain: alignment === FORCED_ALIGNMENT && probability === 0
    };
    const candidates = [word.word, word.word.replace(EDGE_PUNCTUATION_RE, "")].filter(
      (candidate) => candidate.length > 0
    );
    for (const candidate of candidates) {
      const at = text.indexOf(candidate, cursor);
      if (at < 0) continue;
      located.charStart = at;
      located.charEnd = at + candidate.length;
      cursor = located.charEnd;
      break;
    }
    return located;
  });
}

/**
 * Segments with their stored word timings attached. A stale or missing
 * payload leaves the segments untouched (segment-level playback only).
 */
export function attachWords(
  segments: readonly TranscriptSegment[],
  payload: TranscriptWordsPayload | null | undefined
): TranscriptSegment[] {
  if (!payload || payload.stale || !Array.isArray(payload.segments)) return [...segments];
  const bySegment = new Map<number, TranscriptWirePayloadWord[]>();
  for (const entry of payload.segments) {
    if (Array.isArray(entry?.words)) bySegment.set(entry.segment_index, entry.words);
  }
  return segments.map((segment) => {
    const words = bySegment.get(segment.index);
    if (!words || words.length === 0) return segment;
    return { ...segment, words: locateWords(segment.text, words, payload.alignment) };
  });
}

/** How many words across `segments` the aligner could not place. */
export function countUncertainWords(segments: readonly TranscriptSegment[]): number {
  let count = 0;
  for (const segment of segments) {
    for (const word of segment.words ?? []) if (word.uncertain) count += 1;
  }
  return count;
}

/**
 * The word playing at `time` within one segment's words, or -1. Between two
 * words the earlier one stays active so the highlight does not flicker.
 */
export function findActiveWordIndex(
  words: readonly TranscriptWord[],
  time: number,
  lastIndex = -1
): number {
  const last = words[lastIndex];
  if (last && last.start <= time) {
    const next = words[lastIndex + 1];
    if (!next || time < next.start) return lastIndex;
  }
  let result = -1;
  let low = 0;
  let high = words.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (words[mid].start <= time) {
      result = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return result;
}

type Payload = Record<string, unknown> | null | undefined;

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Segments the transcription step stored, or null when it stored none. */
export function segmentsFromMetadata(transcription: Payload): TranscriptSegment[] | null {
  const raw = transcription?.segments;
  if (!Array.isArray(raw)) return null;
  const segments: TranscriptSegment[] = [];
  for (const item of raw) {
    const entry = record(item);
    if (!entry) continue;
    const start = finite(entry.start);
    const end = finite(entry.end);
    if (start === null || end === null || typeof entry.text !== "string") continue;
    const fileIndex = finite(entry.file_index) ?? 0;
    segments.push({
      index: segments.length,
      fileIndex,
      start,
      end: Math.max(start, end),
      speaker: typeof entry.speaker === "string" && entry.speaker ? entry.speaker : null,
      text: entry.text
    });
  }
  return segments.length > 0 ? segments : null;
}

// `[HH:MM:SS - HH:MM:SS] LABEL: text`; the label is a diarization label or,
// after the reviewer named the speakers, a person's name.
const LINE_RE = /^\[(\d{2,}):(\d{2}):(\d{2}) - (\d{2,}):(\d{2}):(\d{2})\](?: ([^:\n]+?):)? ?(.*)$/;
// Multi-file transcripts are joined with a header per recording part.
const PART_HEADER_RE = /^## Del (\d+)\b/;

function seconds(h: string, m: string, s: string): number {
  return Number(h) * 3600 + Number(m) * 60 + Number(s);
}

/** Fallback for transcripts without stored segments: parse the rendered lines. */
export function parseTranscript(text: string): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  let fileIndex = 0;
  for (const line of text.split("\n")) {
    const header = PART_HEADER_RE.exec(line);
    if (header) {
      fileIndex = Math.max(0, Number(header[1]) - 1);
      continue;
    }
    const match = LINE_RE.exec(line);
    if (!match) continue;
    const start = seconds(match[1], match[2], match[3]);
    const end = seconds(match[4], match[5], match[6]);
    segments.push({
      index: segments.length,
      fileIndex,
      start,
      end: Math.max(start, end),
      speaker: match[7] ?? null,
      text: match[8] ?? ""
    });
  }
  return segments;
}

/**
 * True when the text is nothing but a transcript: every non-blank line is a
 * timestamped line or a part header. A document that merely quotes transcript
 * lines (a title, notes) is not one.
 */
export function isPureTranscript(text: string): boolean {
  let lines = 0;
  for (const line of text.split("\n")) {
    if (line.trim() === "" || PART_HEADER_RE.test(line)) continue;
    if (!LINE_RE.test(line)) return false;
    lines += 1;
  }
  return lines > 0;
}

/** Number of audio files the segments span (at least one). */
export function countFiles(segments: readonly TranscriptSegment[]): number {
  return segments.reduce((max, segment) => Math.max(max, segment.fileIndex + 1), 1);
}

/** Speaker labels replaced by the names the reviewer assigned; unmapped stay. */
export function applySpeakerNames(
  segments: readonly TranscriptSegment[],
  names: Readonly<Record<string, string | null | undefined>>
): TranscriptSegment[] {
  return segments.map((segment) => {
    const name = segment.speaker ? names[segment.speaker]?.trim() : undefined;
    return name ? { ...segment, speaker: name } : segment;
  });
}

/**
 * The segment playing at `time` in `fileIndex`, or -1. Between two segments
 * the earlier one stays active so the highlight does not flicker in pauses.
 */
export function findActiveSegmentIndex(
  segments: readonly TranscriptSegment[],
  fileIndex: number,
  time: number,
  lastIndex = -1
): number {
  const last = segments[lastIndex];
  if (last && last.fileIndex === fileIndex && last.start <= time) {
    const next = segments[lastIndex + 1];
    if (!next || next.fileIndex !== fileIndex || time < next.start) return lastIndex;
  }
  let result = -1;
  let low = 0;
  let high = segments.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const segment = segments[mid];
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

export const SPEAKER_PALETTE_SIZE = 8;

/** Stable palette slot for a speaker label so a person keeps a colour. */
export function speakerColorIndex(label: string): number {
  const numbered = /^SPEAKER_(\d+)$/.exec(label);
  if (numbered) return Number(numbered[1]) % SPEAKER_PALETTE_SIZE;
  let hash = 0;
  for (const char of label) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % SPEAKER_PALETTE_SIZE;
}

/** `HH:MM:SS`, or `MM:SS` when the whole transcript is under an hour. */
export function formatClock(totalSeconds: number, withHours = false): string {
  const whole = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return withHours || h > 0 ? `${String(h).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`;
}
