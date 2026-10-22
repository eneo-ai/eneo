/**
 * What a recording can tell support when it misbehaves: the recorder's
 * state, what the browser supports, the format, the microphone's settings,
 * the step's parts, the timings and the recent events. Nothing personal goes
 * in: no device names or ids, no audio, no text, no file names, no ids of
 * the flow, run or recording.
 */

/** Something that happened to the recording, at a time relative to the recorder's first event. */
export type RecorderEvent = { atMs: number; event: string; detail?: string };

/** The most recent events a report carries. */
export const MAX_RECORDER_EVENTS = 50;

/** The recent events, oldest first, with times on the recorder's monotonic clock. */
export class RecorderEventLog {
  #events: RecorderEvent[] = [];
  #origin: number | null = null;
  #now: () => number;

  constructor(now: () => number) {
    this.#now = now;
  }

  add(event: string, detail?: string): void {
    const at = this.#now();
    this.#origin ??= at;
    this.#events.push({
      atMs: Math.round(at - this.#origin),
      event,
      ...(detail ? { detail } : {})
    });
    if (this.#events.length > MAX_RECORDER_EVENTS) this.#events.shift();
  }

  list(): RecorderEvent[] {
    return this.#events.map((entry) => ({ ...entry }));
  }
}

/** The microphone settings worth telling: how it records, never which device it is. */
const SETTING_KEYS = [
  "sampleRate",
  "sampleSize",
  "channelCount",
  "echoCancellation",
  "noiseSuppression",
  "autoGainControl",
  "latency"
] as const;

export type MicrophoneSettings = Partial<Record<(typeof SETTING_KEYS)[number], number | boolean>>;

/** The track's settings without `deviceId`, `groupId` or anything else that names the device. */
export function microphoneSettings(
  settings: MediaTrackSettings | undefined | null
): MicrophoneSettings | null {
  if (!settings) return null;
  const picked: MicrophoneSettings = {};
  for (const key of SETTING_KEYS) {
    const value = (settings as Record<string, unknown>)[key];
    if (typeof value === "number" || typeof value === "boolean") picked[key] = value;
  }
  return picked;
}

/** The recorder's own part of a report. */
export type RecorderDiagnostics = {
  phase: string;
  problem: string | null;
  ended: string | null;
  support: { secureContext: boolean; mediaRecorder: boolean; audioContext: boolean };
  format: { requested: string | null; recorder: string | null; audioBitsPerSecond: number };
  microphone: {
    /** Which constraints the browser accepted: the preferred ones or the looser retry. */
    constraints: "preferred" | "relaxed" | null;
    settings: MicrophoneSettings | null;
    /** How many microphones the browser said it has, after one could not be opened. */
    inputs: number | null;
    muted: boolean;
  };
  meter: { state: string; sampleRate: number } | null;
  recording: {
    recordedMs: number;
    partsThisStart: number;
    /** The part being recorded: its place, chunks and bytes so far. */
    part: { index: number; chunks: number; bytes: number } | null;
    pendingParts: number;
    emptyChunks: number;
    firstChunkAfterMs: number | null;
    lastChunkAgoMs: number | null;
    micHint: string | null;
  };
  events: RecorderEvent[];
};

/** A recorded part of the step as the form holds it. */
export type PartDiagnostics = {
  index: number;
  durationMs: number;
  bytes: number;
  upload: string;
  retryable: boolean;
  /** Where the part is kept: on the device, only in this tab, or still being stored. */
  kept: string;
};

export type RecordingReport = {
  generatedAt: string;
  browser: string;
  recorder: RecorderDiagnostics;
  parts: PartDiagnostics[];
  storage: string;
  live: string | null;
};

/** The report as the text that is shown and copied. */
export function reportText(report: RecordingReport): string {
  return JSON.stringify(report, null, 2);
}
