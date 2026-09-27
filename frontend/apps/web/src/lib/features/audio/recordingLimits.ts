// A recording's length and parts, from the audio step in Eneo's run contract:
// the longest recording (an admin's setting) and the part length at which the
// step's file slots hold it.

import type { FlowRunContractStepInput } from "@eneo/eneo-js";

import { selectAudioRecordingOptions } from "./audioRecordingOptions";

export type RecordingLimits = {
  partMs: number | null;
  maxRecordingMs: number | null;
};

// Opus and AAC swing around their bit rate and the container adds a little, so a
// part aims at nine tenths of a file's size limit.
const FILE_SIZE_SHARE = 0.9;

// Recorded time is measured on a monotonic clock: a system clock set back or
// forward during a meeting must not change how long the recording is.
export const monotonicNow = (): number => performance.now();

// As Eneo's contract asks, a part starts at recording_part_seconds, or earlier where
// it nears the time or size one file may hold (at this browser's bit rate).
export function recordingLimitsForStep(
  step: Pick<
    FlowRunContractStepInput,
    | "max_files"
    | "max_duration_seconds"
    | "max_file_size_bytes"
    | "max_recording_seconds"
    | "recording_part_seconds"
  >,
  audioBitsPerSecond: number = selectAudioRecordingOptions().audioBitsPerSecond
): RecordingLimits {
  // An Eneo without the recording fields decodes a recording under its time per file.
  const whole = step.max_recording_seconds ? step.max_recording_seconds * 1000 : null;
  const perFile = step.max_duration_seconds ? step.max_duration_seconds * 1000 : null;
  const maxRecordingMs = whole ?? perFile;
  const contractPart = step.recording_part_seconds
    ? step.recording_part_seconds * 1000
    : maxRecordingMs && step.max_files
      ? Math.ceil(maxRecordingMs / step.max_files / 1000) * 1000
      : maxRecordingMs;
  const partMs = Math.min(
    contractPart ?? Infinity,
    whole && perFile ? perFile - limitRoomMs(perFile) : Infinity,
    step.max_file_size_bytes
      ? ((step.max_file_size_bytes * 8 * FILE_SIZE_SHARE) / audioBitsPerSecond) * 1000
      : Infinity
  );
  return { partMs: Number.isFinite(partMs) ? partMs : null, maxRecordingMs };
}

// Room per handover: the parts overlap, by up to about a second in a hidden tab.
const HANDOVER_ROOM_MS = 1_000;

// Room below the limit for a timer a hidden tab fires late and the page's clock
// against the decoded audio: a minute, or 5 % of a limit under 20 minutes, never
// under two seconds.
const limitRoomMs = (limitMs: number) =>
  Math.max(limitMs < 20 * 60_000 ? limitMs * 0.05 : 60_000, 2_000);

// Recorded time a recording of `parts` parts (the running one included) and
// `recordedMs` has left before the longest recording; Infinity without one.
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

// Recorded time a recording started now may still hold, within what the free file
// slots hold at the part length: a new recording is said by Eneo's own limit, a
// continued one by the time it may still record (as the recording stops by it).
// Null without either limit.
export function recordingRoomMs(limits: {
  partMs: number | null;
  maxRecordingMs: number | null;
  recordedMs: number;
  parts: number;
  filesLeft: number;
}): number | null {
  const room = Math.min(
    limits.parts === 0
      ? (limits.maxRecordingMs ?? Infinity)
      : recordingTimeLeftMs(limits.maxRecordingMs, limits.parts + 1, limits.recordedMs),
    limits.partMs === null ? Infinity : Math.max(0, limits.filesLeft) * limits.partMs
  );
  return Number.isFinite(room) ? Math.max(0, room) : null;
}

// "5 h", "4 h 30 min" or "45 min": a recording limit as the dialog says it.
export function formatRecordingLength(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  const hours = Math.floor(minutes / 60);
  if (hours === 0) return `${minutes} min`;
  return minutes % 60 === 0 ? `${hours} h` : `${hours} h ${minutes % 60} min`;
}
