// A recording's length and parts, from the audio step in Eneo's run contract:
// the longest recording (an admin's setting) and the part length at which the
// step's file slots hold it.

import type { FlowRunContractStepInput } from "@eneo/eneo-js";

export type RecordingLimits = {
  partMs: number | null;
  maxRecordingMs: number | null;
};

// Recorded time is measured on a monotonic clock: a system clock set back or
// forward during a meeting must not change how long the recording is.
export const monotonicNow = (): number => performance.now();

export function recordingLimitsForStep(
  step: Pick<
    FlowRunContractStepInput,
    "max_files" | "max_duration_seconds" | "max_recording_seconds" | "recording_part_seconds"
  >
): RecordingLimits {
  // An Eneo without the recording fields decodes a recording under its time per file.
  const whole = step.max_recording_seconds ?? step.max_duration_seconds ?? null;
  const part =
    step.recording_part_seconds ??
    (whole && step.max_files ? Math.ceil(whole / step.max_files) : whole);
  return {
    partMs: part ? part * 1000 : null,
    maxRecordingMs: whole ? whole * 1000 : null
  };
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

// "5 h", "4 h 30 min" or "45 min": a recording limit as the dialog says it.
export function formatRecordingLength(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  const hours = Math.floor(minutes / 60);
  if (hours === 0) return `${minutes} min`;
  return minutes % 60 === 0 ? `${hours} h` : `${hours} h ${minutes % 60} min`;
}
