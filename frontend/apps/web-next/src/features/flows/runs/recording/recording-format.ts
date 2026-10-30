import type { RuntimeInput } from "../runs-api";

/**
 * What a recording in the run form is made of: the format this browser
 * records in, the file name of each part, and how long a part and the whole
 * recording may be by the audio step's run contract.
 */

export type RecordingOptions = { mimeType?: string; audioBitsPerSecond: number };

/** Speech in Opus is clear at 24 kbit/s; AAC needs more for the same. */
export const SPEECH_OPUS_BITRATE = 24_000;
export const SPEECH_AAC_BITRATE = 64_000;

const CANDIDATES: RecordingOptions[] = [
  { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: SPEECH_OPUS_BITRATE },
  { mimeType: "audio/ogg;codecs=opus", audioBitsPerSecond: SPEECH_OPUS_BITRATE },
  { mimeType: "audio/mp4;codecs=mp4a.40.2", audioBitsPerSecond: SPEECH_AAC_BITRATE },
  { mimeType: "audio/mp4", audioBitsPerSecond: SPEECH_AAC_BITRATE },
  { mimeType: "video/webm;codecs=opus", audioBitsPerSecond: SPEECH_OPUS_BITRATE }
];

/** The first speech format the browser records, or its own default. */
export function selectRecordingOptions(
  isTypeSupported: (mimeType: string) => boolean
): RecordingOptions {
  const supported = CANDIDATES.find(({ mimeType }) => {
    try {
      return mimeType ? isTypeSupported(mimeType) : false;
    } catch {
      return false;
    }
  });
  return supported ?? { audioBitsPerSecond: SPEECH_AAC_BITRATE };
}

/** The file extension of a recorded type: `webm`, `ogg`, `m4a`. */
export function extensionFor(mimeType: string): string {
  const type = mimeType.split(";", 1)[0]?.trim().toLowerCase() ?? "";
  switch (type) {
    case "audio/mp4":
    case "video/mp4":
      return "m4a";
    case "audio/webm":
    case "video/webm":
      return "webm";
    case "audio/ogg":
      return "ogg";
    case "audio/mpeg":
      return "mp3";
    default:
      return type.split("/")[1] || "audio";
  }
}

/**
 * A part's file name, which the core reads back to order a recording's parts
 * and place them in time (`transcription.py`, `_SEGMENT_FILENAME_RE`):
 * `recording-<session>-segNN-<UTC time with - for : and .>Z.<ext>`.
 */
export function partFileName(
  sessionId: string,
  index: number,
  capturedAt: number,
  mimeType: string
): string {
  const time = new Date(capturedAt).toISOString().replace(/[:.]/g, "-");
  return `recording-${sessionId}-seg${String(index).padStart(2, "0")}-${time}.${extensionFor(mimeType)}`;
}

/** Whether a step's files may be recorded: it takes audio in a type this browser records. */
export function recordsInto(
  input: Pick<RuntimeInput, "input_format" | "accepted_mimetypes">,
  mimeType: string | undefined
): boolean {
  if (input.input_format !== "audio") return false;
  const accepted = input.accepted_mimetypes ?? [];
  if (accepted.length === 0) return true;
  const type = (mimeType ?? "").split(";", 1)[0]?.trim().toLowerCase() ?? "";
  // The browser's own default type is only known once it records.
  if (!type) return true;
  return accepted.some((entry) => {
    const allowed = entry.toLowerCase();
    return allowed.endsWith("/*") ? type.startsWith(allowed.slice(0, -1)) : type === allowed;
  });
}

export type RecordingLimits = {
  /** Start a new part at this recorded length; null for one part. */
  partMs: number | null;
  /** The longest recording; null when the step sets none. */
  maxRecordingMs: number | null;
};

/** Opus and AAC swing around their bit rate: a part aims at nine tenths of a file's size limit. */
const FILE_SIZE_SHARE = 0.9;

/**
 * Room below a limit for a timer a hidden tab fires late and for the page's
 * clock against the decoded audio: a minute, or 5 % of a limit under 20
 * minutes, never under two seconds.
 */
export function limitRoomMs(limitMs: number): number {
  return Math.max(limitMs < 20 * 60_000 ? limitMs * 0.05 : 60_000, 2_000);
}

/** Parts overlap a little at each handover. */
const HANDOVER_ROOM_MS = 1_000;

/**
 * As the run contract asks: a part starts at `recording_part_seconds`, or
 * earlier where it nears the time or the size one file may hold at this
 * browser's bit rate; the whole recording stops by `max_recording_seconds`
 * (an older core states only the time per file).
 */
export function recordingLimits(
  input: Pick<
    RuntimeInput,
    | "max_files"
    | "max_duration_seconds"
    | "max_file_size_bytes"
    | "max_recording_seconds"
    | "recording_part_seconds"
  >,
  audioBitsPerSecond: number
): RecordingLimits {
  const whole = input.max_recording_seconds ? input.max_recording_seconds * 1000 : null;
  const perFile = input.max_duration_seconds ? input.max_duration_seconds * 1000 : null;
  const maxRecordingMs = whole ?? perFile;
  const contractPart = input.recording_part_seconds
    ? input.recording_part_seconds * 1000
    : maxRecordingMs && input.max_files
      ? Math.ceil(maxRecordingMs / input.max_files / 1000) * 1000
      : maxRecordingMs;
  const partMs = Math.min(
    contractPart ?? Infinity,
    whole && perFile ? perFile - limitRoomMs(perFile) : Infinity,
    input.max_file_size_bytes
      ? ((input.max_file_size_bytes * 8 * FILE_SIZE_SHARE) / audioBitsPerSecond) * 1000
      : Infinity
  );
  return { partMs: Number.isFinite(partMs) ? partMs : null, maxRecordingMs };
}

/**
 * Recorded time left before the longest recording, for a recording of
 * `parts` parts (the running one included) holding `recordedMs`; Infinity
 * without a limit.
 */
export function recordingTimeLeftMs(
  maxRecordingMs: number | null,
  parts: number,
  recordedMs: number
): number {
  if (!maxRecordingMs) return Infinity;
  return (
    maxRecordingMs -
    limitRoomMs(maxRecordingMs) -
    Math.max(0, parts - 1) * HANDOVER_ROOM_MS -
    recordedMs
  );
}

/** `12:05` or `1:02:05`: a recorded length on the recorder's clock. */
export function clockText(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

/** Whole minutes and hours of a limit, for "up to {hours} h {minutes} min". */
export function lengthParts(ms: number): { hours: number; minutes: number } {
  const minutes = Math.max(1, Math.round(ms / 60_000));
  return { hours: Math.floor(minutes / 60), minutes: minutes % 60 };
}
