// Owns rotation and retry around the single-clip recorder.

import type { ContractSnapshot } from "./recordingSessionStore";
import type { RecordingStopReason } from "./recordedAudioFile";

export const SEGMENT_ROTATION_MS = 20 * 60 * 1000;
export const RETRY_BACKOFF_MS = [1_000, 2_000, 4_000] as const;
export const MAX_RETRY_ATTEMPTS = 3;
export const RETRY_WALL_CLOCK_CAP_MS = 30_000;
const RECORDING_FILENAME_PREFIX = "recording-";

export type SessionState = "idle" | "recording" | "rotating" | "reconnecting" | "paused-failed";

export type SegmentStartOutcome = { ok: true } | { ok: false; error: unknown };

export type RecordingSessionDeps = {
  startSegment: () => Promise<SegmentStartOutcome>;
  stopSegment: (reason: RecordingStopReason) => void;
};

export type RecordingSessionEventListeners = {
  onStateChange?: (state: SessionState) => void;
  onAutoRecovered?: () => void;
  onRetryFailed?: () => void;
};

// On resume, the live flow contract may differ from what was active when the
// recording started. The dialog branches on `severity`:
//   warn         - inform the user but allow continue/submit
//   block-resume - cannot start a new segment against this flow safely
//   block-submit - the segments we have can't be attached as-is
export type ContractMismatchIssue =
  | { kind: "version-bump"; oldVersion: number | null; newVersion: number | null; severity: "warn" }
  | { kind: "step-removed"; severity: "block-resume" }
  | {
      kind: "input-format-changed";
      oldFormat: string | null;
      newFormat: string | null;
      severity: "block-resume";
    }
  | {
      kind: "max-files-shrunk";
      oldMax: number | null;
      newMax: number | null;
      segmentCount: number;
      severity: "block-submit";
    }
  | { kind: "max-file-size-shrunk"; oldMax: number | null; newMax: number | null; severity: "warn" }
  | {
      kind: "mimes-narrowed";
      oldMimes: string[];
      newMimes: string[];
      segmentMimes: string[];
      severity: "block-submit";
    };

export function generateSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const rand = () => Math.random().toString(16).slice(2, 10);
  return `${rand()}${rand()}-${rand()}-${rand()}-${rand()}-${rand()}${rand()}${rand()}`;
}

export function buildSegmentFilenameBase(
  sessionId: string,
  segmentIndex: number,
  capturedAt: number
): string {
  // Keep aligned with backend/src/eneo/flows/runtime/transcription.py::_SEGMENT_FILENAME_RE.
  const iso = new Date(capturedAt).toISOString().replace(/[:.]/g, "-");
  const seg = segmentIndex.toString().padStart(2, "0");
  return `${RECORDING_FILENAME_PREFIX}${sessionId}-seg${seg}-${iso}`;
}

export function segmentExtensionFromMime(mimeType: string): string {
  const normalized = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";
  switch (normalized) {
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
    default: {
      const subtype = normalized.split("/")[1];
      return subtype && subtype.length > 0 ? subtype : "audio";
    }
  }
}

export function diffContractSnapshot(
  snapshot: ContractSnapshot,
  current: ContractSnapshot,
  segments: { mimeType: string; bytes: number }[]
): ContractMismatchIssue[] {
  const issues: ContractMismatchIssue[] = [];

  if (current.inputFormat === null) {
    issues.push({ kind: "step-removed", severity: "block-resume" });
    return issues;
  }
  if (snapshot.inputFormat !== null && current.inputFormat !== snapshot.inputFormat) {
    issues.push({
      kind: "input-format-changed",
      oldFormat: snapshot.inputFormat,
      newFormat: current.inputFormat,
      severity: "block-resume"
    });
    return issues;
  }
  if ((snapshot.publishedFlowVersion ?? null) !== (current.publishedFlowVersion ?? null)) {
    issues.push({
      kind: "version-bump",
      oldVersion: snapshot.publishedFlowVersion,
      newVersion: current.publishedFlowVersion,
      severity: "warn"
    });
  }
  if (
    typeof current.maxFiles === "number" &&
    Number.isFinite(current.maxFiles) &&
    segments.length > current.maxFiles
  ) {
    issues.push({
      kind: "max-files-shrunk",
      oldMax: snapshot.maxFiles,
      newMax: current.maxFiles,
      segmentCount: segments.length,
      severity: "block-submit"
    });
  }
  if (
    typeof current.maxFileSizeBytes === "number" &&
    Number.isFinite(current.maxFileSizeBytes) &&
    typeof snapshot.maxFileSizeBytes === "number" &&
    snapshot.maxFileSizeBytes > current.maxFileSizeBytes
  ) {
    issues.push({
      kind: "max-file-size-shrunk",
      oldMax: snapshot.maxFileSizeBytes,
      newMax: current.maxFileSizeBytes,
      severity: "warn"
    });
  }
  if (current.acceptedMimetypes.length > 0) {
    const allowed = new Set(current.acceptedMimetypes.map((m) => m.toLowerCase()));
    const offending = segments
      .map((s) => s.mimeType.split(";")[0].trim().toLowerCase())
      .filter((mime) => mime.length > 0 && !allowed.has(mime));
    if (offending.length > 0) {
      issues.push({
        kind: "mimes-narrowed",
        oldMimes: snapshot.acceptedMimetypes,
        newMimes: current.acceptedMimetypes,
        segmentMimes: offending,
        severity: "block-submit"
      });
    }
  }

  return issues;
}

export type RecordingSessionSummary = {
  state: SessionState;
  sessionId: string | null;
  retryAttempt: number;
};

export class RecordingSession {
  private _state: SessionState = "idle";
  private _sessionId: string | null = null;
  private _retryAttempts = 0;
  private _retryWallClockStart: number | null = null;
  private _rotationTimer: ReturnType<typeof setTimeout> | null = null;
  private _retryTimer: ReturnType<typeof setTimeout> | null = null;
  private _disposed = false;
  private _now: () => number;

  constructor(
    private deps: RecordingSessionDeps,
    private listeners: RecordingSessionEventListeners,
    options: { now?: () => number } = {}
  ) {
    this._now = options.now ?? (() => Date.now());
  }

  summary(): RecordingSessionSummary {
    return {
      state: this._state,
      sessionId: this._sessionId,
      retryAttempt: this._retryAttempts
    };
  }

  // Why a separate "external" entry point: the AudioRecorder owns its
  // own start button, so when the user clicks Start the recorder
  // begins capture *before* the dialog hands the session control. We
  // can't call deps.startSegment in that path because the recorder is
  // already running. beginRecordingExternal sets up the session bookkeeping
  // and arms the rotation timer
  // without triggering deps.startSegment.
  beginRecordingExternal(): void {
    if (this._disposed) return;

    // User pressed Record while we were waiting on a queued retry. Pre-empt
    // the retry rather than letting it fire 1-4 s later on top of the
    // recording the user has just kicked off. Keep the existing session
    // id; only the retry bookkeeping resets.
    if (this._state === "reconnecting") {
      this.cancelRetryTimer();
      this._retryAttempts = 0;
      this._retryWallClockStart = null;
      this.transitionTo("recording");
      this.armRotationTimer();
      return;
    }

    if (this._state !== "idle") {
      return;
    }
    this._sessionId = generateSessionId();
    this._retryAttempts = 0;
    this._retryWallClockStart = null;
    this.transitionTo("recording");
    this.armRotationTimer();
  }

  dispose(): void {
    this._disposed = true;
    this.cancelRotationTimer();
    this.cancelRetryTimer();
  }

  notifyHardFailure(): void {
    if (this._state === "recording" || this._state === "rotating") {
      this.transitionTo("reconnecting");
      this.scheduleRetry();
    }
  }

  private async attemptStartSegment(): Promise<SegmentStartOutcome> {
    return this.deps.startSegment();
  }

  private armRotationTimer(): void {
    this.cancelRotationTimer();
    this._rotationTimer = setTimeout(() => {
      this._rotationTimer = null;
      if (this._state === "recording") {
        this.transitionTo("rotating");
        this.deps.stopSegment("rotation");
      }
    }, SEGMENT_ROTATION_MS);
  }

  private cancelRotationTimer(): void {
    if (this._rotationTimer !== null) {
      clearTimeout(this._rotationTimer);
      this._rotationTimer = null;
    }
  }

  private scheduleRetry(): void {
    if (this._retryWallClockStart === null) {
      this._retryWallClockStart = this._now();
    }
    const elapsed = this._now() - this._retryWallClockStart;
    if (elapsed > RETRY_WALL_CLOCK_CAP_MS) {
      this.transitionTo("paused-failed");
      this.listeners.onRetryFailed?.();
      return;
    }
    if (this._retryAttempts >= MAX_RETRY_ATTEMPTS) {
      this.transitionTo("paused-failed");
      this.listeners.onRetryFailed?.();
      return;
    }

    const attempt = this._retryAttempts;
    const backoff = RETRY_BACKOFF_MS[attempt] ?? RETRY_BACKOFF_MS[RETRY_BACKOFF_MS.length - 1];
    const sessionId = this._sessionId;

    this.cancelRetryTimer();
    this._retryTimer = setTimeout(async () => {
      this._retryTimer = null;
      // Dispose or a fresh start can land between scheduling and firing;
      // bail without touching state if either happened.
      if (this._disposed || this._state !== "reconnecting" || this._sessionId !== sessionId) {
        return;
      }
      this._retryAttempts += 1;
      const outcome = await this.attemptStartSegment();
      if (this._disposed || this._sessionId !== sessionId) return;
      if (outcome.ok) {
        this._retryAttempts = 0;
        this._retryWallClockStart = null;
        this.transitionTo("recording");
        this.armRotationTimer();
        this.listeners.onAutoRecovered?.();
      } else {
        this.scheduleRetry();
      }
    }, backoff);
  }

  private cancelRetryTimer(): void {
    if (this._retryTimer !== null) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
  }

  private transitionTo(next: SessionState): void {
    if (this._state === next) return;
    this._state = next;
    this.listeners.onStateChange?.(next);
  }
}
