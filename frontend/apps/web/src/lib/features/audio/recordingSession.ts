// Multi-segment recording session.
//
// Wraps a single-segment recorder with three behaviours that the underlying
// MediaRecorder cannot do alone: auto-retry on stream interruption (track
// ended, encoder error, watchdog stall), proactive rotation every 20 minutes
// so each clip stays under the transcription provider's per-file caps, and an
// IndexedDB ledger so a tab refresh during a 3-hour recording loses at most
// the segment that's currently being captured — every previously rotated
// segment stays recoverable from the resume prompt.
//
// Pure TypeScript on purpose — no Svelte runes — so the state machine is
// unit-testable without a renderer. Callers wire the SingleSegmentRecorder
// callbacks (`AudioRecorder.svelte`) to the deps below.

import { recordingSessionStore, SESSION_RECOVERY_TTL_MS } from "./recordingSessionStore";
import type {
  ContractSnapshot,
  SegmentRecord,
  SessionRecoveryHint,
  StoreMode
} from "./recordingSessionStore";
import type { RecordingStopReason } from "./recordedAudioFile";

export const SEGMENT_ROTATION_MS = 20 * 60 * 1000;
export const RETRY_BACKOFF_MS = [1_000, 2_000, 4_000] as const;
export const MAX_RETRY_ATTEMPTS = 3;
export const RETRY_WALL_CLOCK_CAP_MS = 30_000;
const RECORDING_FILENAME_PREFIX = "recording-";

export type SessionState =
  | "idle"
  | "preparing"
  | "recording"
  | "rotating"
  | "reconnecting"
  | "paused-failed"
  | "completed"
  | "discarded";

export type SegmentStartOutcome = { ok: true } | { ok: false; error: unknown };

export type SegmentFinalizedInput = {
  blob: Blob;
  mimeType: string;
  reason: RecordingStopReason;
  durationMs: number;
};

export type UploadResult = { ok: true; fileId: string } | { ok: false; error: unknown };

export type RecordingSessionDeps = {
  startSegment: () => Promise<SegmentStartOutcome>;
  stopSegment: (reason: RecordingStopReason) => void;
  uploadSegment: (file: File) => Promise<UploadResult>;
  deleteUploadedSegment: (fileId: string) => Promise<void>;
};

export type RecordingSessionEventListeners = {
  onStateChange?: (state: SessionState) => void;
  onSegmentsChanged?: (segments: ReadonlyArray<SessionSegment>) => void;
  onAutoRecovered?: () => void;
  onRetryFailed?: () => void;
  onUploadFailed?: (segment: SessionSegment, error: unknown) => void;
  onPersistenceModeChanged?: (mode: StoreMode) => void;
  onContractMismatch?: (issue: ContractMismatchIssue) => void;
};

export type SessionSegment = {
  segmentIndex: number;
  durationMs: number;
  bytes: number;
  mimeType: string;
  capturedAt: number;
  uploadedFileId: string | null;
  uploadFailed: boolean;
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
  const iso = new Date(capturedAt).toISOString().replace(/[:.]/g, "-");
  const seg = segmentIndex.toString().padStart(2, "0");
  return `${RECORDING_FILENAME_PREFIX}${sessionId}-seg${seg}-${iso}`;
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

type RetryAttempt = {
  attempt: number;
  startedAt: number;
};

export type RecordingSessionSummary = {
  state: SessionState;
  sessionId: string | null;
  segments: ReadonlyArray<SessionSegment>;
  totalDurationMs: number;
  totalBytes: number;
  uploadedSegmentCount: number;
  failedUploadCount: number;
  retryAttempt: number;
  persistenceMode: StoreMode;
  contractIssues: ContractMismatchIssue[];
};

export class RecordingSession {
  private _state: SessionState = "idle";
  private _segments: SessionSegment[] = [];
  private _sessionId: string | null = null;
  private _flowId: string | null = null;
  private _stepId: string | null = null;
  private _contractSnapshot: ContractSnapshot | null = null;
  private _uploadedFileIds: string[] = [];
  private _segmentFilenameBase = (i: string, n: number, t: number) =>
    buildSegmentFilenameBase(i, n, t);
  private _startedAt: number = 0;
  private _retryAttempts: RetryAttempt[] = [];
  private _retryWallClockStart: number | null = null;
  private _rotationTimer: ReturnType<typeof setTimeout> | null = null;
  private _retryTimer: ReturnType<typeof setTimeout> | null = null;
  private _persistenceMode: StoreMode = "indexeddb";
  private _contractIssues: ContractMismatchIssue[] = [];
  private _disposed = false;
  // When the user presses Stop while we're rotating, the recorder has
  // already produced a finalize-in-flight that will arrive with
  // reason==="rotation". Without a stop-intent flag the rotation handler
  // would happily kick off the next segment after the user thought they
  // were done. Read by onSegmentFinalized; cleared by every state-reset.
  private _pendingStopIntent: "user" | null = null;
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
      segments: this._segments,
      totalDurationMs: this._segments.reduce((sum, s) => sum + s.durationMs, 0),
      totalBytes: this._segments.reduce((sum, s) => sum + s.bytes, 0),
      uploadedSegmentCount: this._segments.filter((s) => s.uploadedFileId !== null).length,
      failedUploadCount: this._segments.filter((s) => s.uploadFailed).length,
      retryAttempt: this._retryAttempts.length,
      persistenceMode: this._persistenceMode,
      contractIssues: this._contractIssues
    };
  }

  // Submit order matters: the backend joins transcripts in this order to
  // produce the final text. Sorting by capture index (rather than upload
  // completion) keeps the chronology correct even when uploads finish
  // out-of-order.
  uploadedFileIdsSortedBySegmentIndex(): string[] {
    return [...this._segments]
      .filter((s) => s.uploadedFileId !== null)
      .sort((a, b) => a.segmentIndex - b.segmentIndex)
      .map((s) => s.uploadedFileId as string);
  }

  async start(args: {
    flowId: string;
    stepId: string;
    contractSnapshot: ContractSnapshot;
  }): Promise<SegmentStartOutcome> {
    if (this._disposed) return { ok: false, error: new Error("Session disposed") };
    if (this._state !== "idle" && this._state !== "completed" && this._state !== "discarded") {
      return { ok: false, error: new Error(`Cannot start in state ${this._state}`) };
    }
    // Refuse to fresh-start over recovered or just-recorded segments. The
    // caller should explicitly continueRecording (preserve) or discard
    // (clear) before re-starting; otherwise an accidental Start press
    // would silently wipe the existing audio.
    if (this._segments.length > 0) {
      return {
        ok: false,
        error: new Error(
          "Refusing to start: existing segments must be submitted or discarded first."
        )
      };
    }

    const sessionId = generateSessionId();
    this._sessionId = sessionId;
    this._flowId = args.flowId;
    this._stepId = args.stepId;
    this._contractSnapshot = args.contractSnapshot;
    this._segments = [];
    this._uploadedFileIds = [];
    this._retryAttempts = [];
    this._retryWallClockStart = null;
    this._contractIssues = [];
    this._pendingStopIntent = null;
    this._startedAt = this._now();
    this.transitionTo("preparing");

    const outcome = await this.attemptStartSegment();
    // The session can be disposed or replaced (start/discard from another
    // path) while we await the recorder's getUserMedia; only mutate state
    // if we're still the active session.
    if (this._disposed || this._sessionId !== sessionId) return outcome;
    if (outcome.ok) {
      this.transitionTo("recording");
      this.armRotationTimer();
    } else {
      this.transitionTo("paused-failed");
    }
    return outcome;
  }

  // Why a separate "external" entry point: the AudioRecorder owns its
  // own start button, so when the user clicks Start the recorder
  // begins capture *before* the dialog hands the session control. We
  // can't call deps.startSegment from session.start in that path
  // because the recorder is already running. beginRecordingExternal
  // sets up the same session bookkeeping and arms the rotation timer
  // without triggering deps.startSegment.
  beginRecordingExternal(args: {
    flowId: string;
    stepId: string;
    contractSnapshot: ContractSnapshot;
  }): void {
    if (this._disposed) return;

    // User pressed Record while we were waiting on a queued retry. Pre-empt
    // the retry rather than letting it fire 1-4 s later on top of the
    // recording the user has just kicked off. Keep the existing session
    // (sessionId, segments, contract) — only the retry bookkeeping resets.
    if (this._state === "reconnecting") {
      this.cancelRetryTimer();
      this._retryAttempts = [];
      this._retryWallClockStart = null;
      this._pendingStopIntent = null;
      this.transitionTo("recording");
      this.armRotationTimer();
      return;
    }

    if (this._state !== "idle" && this._state !== "completed" && this._state !== "discarded") {
      return;
    }
    // Same guard as start(): never silently overwrite recovered or
    // just-finished segments. The caller must use continueRecordingExternal
    // when there is something to preserve.
    if (this._segments.length > 0) {
      console.warn(
        "RecordingSession.beginRecordingExternal: refusing to start over existing segments — call continueRecordingExternal or discard first."
      );
      return;
    }
    this._sessionId = generateSessionId();
    this._flowId = args.flowId;
    this._stepId = args.stepId;
    this._contractSnapshot = args.contractSnapshot;
    this._segments = [];
    this._uploadedFileIds = [];
    this._retryAttempts = [];
    this._retryWallClockStart = null;
    this._contractIssues = [];
    this._pendingStopIntent = null;
    this._startedAt = this._now();
    this.transitionTo("recording");
    this.armRotationTimer();
  }

  // Counterpart for the resume flow: after resume() leaves the session
  // in "completed", the user can click Start again on the recorder.
  // This method arms the rotation timer for the new segment without
  // re-triggering deps.startSegment.
  continueRecordingExternal(): void {
    if (this._disposed || this._state !== "completed") return;
    this._pendingStopIntent = null;
    this.transitionTo("recording");
    this.armRotationTimer();
  }

  stop(): void {
    if (this._state !== "recording" && this._state !== "rotating") return;
    this.cancelRotationTimer();
    // Mark stop intent BEFORE asking the recorder to stop so a rotation
    // finalize already in-flight is observed and routed to "completed"
    // instead of starting the next segment.
    this._pendingStopIntent = "user";
    this.deps.stopSegment("manual");
  }

  async discard(): Promise<void> {
    this.cancelRotationTimer();
    this.cancelRetryTimer();

    if (this._state === "recording" || this._state === "rotating") {
      this._pendingStopIntent = "user";
      this.deps.stopSegment("manual");
    }

    const flowId = this._flowId;
    const stepId = this._stepId;
    const sessionId = this._sessionId;

    const uploadedFileIds = [...this._uploadedFileIds];
    this._uploadedFileIds = [];
    for (const fileId of uploadedFileIds) {
      try {
        await this.deps.deleteUploadedSegment(fileId);
      } catch (error) {
        // Server delete is best-effort; the orphan janitor sweeps anything
        // we leak within 24 h.
        console.warn("RecordingSession.discard: server delete failed", { fileId, error });
      }
    }

    if (flowId && stepId && sessionId) {
      await recordingSessionStore.deleteSession(flowId, stepId, sessionId);
    }

    this._segments = [];
    this._sessionId = null;
    this._flowId = null;
    this._stepId = null;
    this._contractSnapshot = null;
    this._contractIssues = [];
    this._pendingStopIntent = null;
    this.transitionTo("discarded");
  }

  async markSubmitted(): Promise<void> {
    if (this._flowId && this._stepId && this._sessionId) {
      await recordingSessionStore.deleteSession(this._flowId, this._stepId, this._sessionId);
    }
    this._segments = [];
    this._uploadedFileIds = [];
    this._sessionId = null;
    this._flowId = null;
    this._stepId = null;
    this._contractSnapshot = null;
    this._pendingStopIntent = null;
    this.transitionTo("idle");
  }

  dispose(): void {
    this._disposed = true;
    this.cancelRotationTimer();
    this.cancelRetryTimer();
  }

  async onSegmentFinalized(input: SegmentFinalizedInput): Promise<void> {
    if (this._disposed) return;
    if (!this._sessionId || !this._flowId || !this._stepId || !this._contractSnapshot) {
      console.warn("RecordingSession: segment finalized without active session");
      return;
    }

    // Capture the active session id once; every async continuation below
    // rechecks against this so a session that's been replaced or disposed
    // mid-flight cannot have stale segments grafted onto it.
    const sessionId = this._sessionId;
    const flowId = this._flowId;
    const stepId = this._stepId;
    const contractSnapshot = this._contractSnapshot;

    const segmentIndex = this._segments.length;
    const capturedAt = this._now();

    const segment: SessionSegment = {
      segmentIndex,
      durationMs: input.durationMs,
      bytes: input.blob.size,
      mimeType: input.mimeType,
      capturedAt,
      uploadedFileId: null,
      uploadFailed: false
    };
    this._segments = [...this._segments, segment];
    this.notifySegmentsChanged();

    const filenameBase = this._segmentFilenameBase(sessionId, segmentIndex, capturedAt);
    const file = new File(
      [input.blob],
      `${filenameBase}.${this.extensionForMime(input.mimeType)}`,
      {
        type: input.mimeType
      }
    );

    // Persist before we kick off the upload: a refresh while the upload is
    // in flight must still be recoverable from local storage.
    const persistResult = await recordingSessionStore.writeSegment({
      flowId,
      stepId,
      sessionId,
      segmentIndex,
      blob: input.blob,
      mimeType: input.mimeType,
      durationMs: input.durationMs,
      capturedAt,
      uploadedFileId: null,
      reason: input.reason,
      contractSnapshot
    });
    if (this._disposed || this._sessionId !== sessionId) return;
    if (persistResult.mode !== this._persistenceMode) {
      this._persistenceMode = persistResult.mode;
      this.listeners.onPersistenceModeChanged?.(persistResult.mode);
    }

    // Upload runs alongside the next segment's recording so we don't waste
    // wall-clock on serial upload after the user stops.
    void this.uploadSegmentInBackground(file, segmentIndex, sessionId);

    // Rotation auto-starts the next segment, BUT only if the user hasn't
    // pressed Stop / Discard during the rotation finalize. Without these
    // checks a Stop pressed mid-rotation would still be ignored and the
    // recorder would silently keep going.
    if (input.reason === "rotation") {
      if (this._pendingStopIntent === "user" || this._state !== "rotating") {
        this._pendingStopIntent = null;
        this.cancelRotationTimer();
        this.transitionTo("completed");
        return;
      }
      const outcome = await this.attemptStartSegment();
      if (this._disposed || this._sessionId !== sessionId) return;
      if (outcome.ok) {
        this.transitionTo("recording");
        this.armRotationTimer();
      } else {
        // Rotation start failed: route through the retry loop instead of
        // ending the session, so a transient device hiccup at rotation time
        // doesn't lose the rest of the recording.
        this.transitionTo("reconnecting");
        this.scheduleRetry();
      }
      return;
    }

    if (input.reason === "manual" || input.reason === "limit") {
      this._pendingStopIntent = null;
      this.cancelRotationTimer();
      this.transitionTo("completed");
      return;
    }

    if (input.reason === "stall" || input.reason === "error") {
      this.transitionTo("reconnecting");
      this.scheduleRetry();
      return;
    }
  }

  notifyHardFailure(): void {
    if (this._state === "preparing" || this._state === "recording" || this._state === "rotating") {
      this.transitionTo("reconnecting");
      this.scheduleRetry();
    }
  }

  static async listRecoverable(flowId: string, stepId: string): Promise<SessionRecoveryHint[]> {
    await recordingSessionStore.cleanupExpired();
    return recordingSessionStore.listRecoverableSessions(flowId, stepId);
  }

  async resume(args: {
    flowId: string;
    stepId: string;
    sessionId: string;
    currentContract: ContractSnapshot;
  }): Promise<{ resumed: boolean; issues: ContractMismatchIssue[]; segments: SessionSegment[] }> {
    if (this._disposed) {
      return {
        resumed: false,
        issues: [{ kind: "step-removed", severity: "block-resume" }],
        segments: []
      };
    }

    const records = await recordingSessionStore.readSession(
      args.flowId,
      args.stepId,
      args.sessionId
    );
    if (this._disposed) {
      return { resumed: false, issues: [], segments: [] };
    }
    if (records.length === 0) {
      return { resumed: false, issues: [], segments: [] };
    }

    const snapshot = records[0]!.contractSnapshot;
    const segmentMeta = records.map((r) => ({ mimeType: r.mimeType, bytes: r.blob.size }));
    const issues = diffContractSnapshot(snapshot, args.currentContract, segmentMeta);
    const blockResume = issues.some((i) => i.severity === "block-resume");
    if (blockResume) {
      return {
        resumed: false,
        issues,
        segments: records.map(this.recordToSummarySegment)
      };
    }

    this._sessionId = args.sessionId;
    this._flowId = args.flowId;
    this._stepId = args.stepId;
    this._contractSnapshot = snapshot;
    this._contractIssues = issues;
    this._segments = records.map(this.recordToSummarySegment);
    this._uploadedFileIds = records
      .map((r) => r.uploadedFileId)
      .filter((id): id is string => typeof id === "string" && id.length > 0);
    this._retryAttempts = [];
    this._retryWallClockStart = null;
    this._pendingStopIntent = null;
    this.notifySegmentsChanged();
    // A resumed session sits in `completed` until the user picks
    // continue/submit/discard — we don't auto-resume recording.
    this.transitionTo("completed");

    const resumedSessionId = args.sessionId;
    for (const record of records) {
      if (record.uploadedFileId === null) {
        const filenameBase = this._segmentFilenameBase(
          record.sessionId,
          record.segmentIndex,
          record.capturedAt
        );
        const file = new File(
          [record.blob],
          `${filenameBase}.${this.extensionForMime(record.mimeType)}`,
          { type: record.mimeType }
        );
        void this.uploadSegmentInBackground(file, record.segmentIndex, resumedSessionId);
      }
    }

    return { resumed: true, issues, segments: this._segments };
  }

  async continueRecording(): Promise<SegmentStartOutcome> {
    if (this._state !== "completed") {
      return { ok: false, error: new Error(`Cannot continue from state ${this._state}`) };
    }
    const sessionId = this._sessionId;
    this._pendingStopIntent = null;
    this.transitionTo("preparing");
    const outcome = await this.attemptStartSegment();
    if (this._disposed || this._sessionId !== sessionId) return outcome;
    if (outcome.ok) {
      this.transitionTo("recording");
      this.armRotationTimer();
    } else {
      this.transitionTo("paused-failed");
    }
    return outcome;
  }

  private async attemptStartSegment(): Promise<SegmentStartOutcome> {
    return this.deps.startSegment();
  }

  // The upload runs concurrently with the next segment's recording. Two
  // things can happen while the await is in flight: the user starts a
  // brand-new session (which resets _segments and _sessionId), or the
  // user disposes/discards. In both cases, we still want the IDB ledger
  // patched (so a future resume sees the upload even if the user later
  // re-opens the dialog), but we MUST NOT graft the result onto the
  // current in-memory segments — those belong to a different session.
  private async uploadSegmentInBackground(
    file: File,
    segmentIndex: number,
    sessionId: string
  ): Promise<void> {
    const flowId = this._flowId;
    const stepId = this._stepId;
    if (!flowId || !stepId) return;

    const result = await this.deps.uploadSegment(file);
    const stillActive = !this._disposed && this._sessionId === sessionId;

    if (result.ok) {
      // IDB patch is keyed by the captured session id, so it stays
      // correct regardless of whether the active session has moved on.
      await recordingSessionStore.patchUploadedFileId(
        flowId,
        stepId,
        sessionId,
        segmentIndex,
        result.fileId
      );
      if (!stillActive) return;
      this._uploadedFileIds.push(result.fileId);
      this._segments = this._segments.map((s) =>
        s.segmentIndex === segmentIndex
          ? { ...s, uploadedFileId: result.fileId, uploadFailed: false }
          : s
      );
      this.notifySegmentsChanged();
      return;
    }

    if (!stillActive) return;
    const segment = this._segments.find((s) => s.segmentIndex === segmentIndex);
    this._segments = this._segments.map((s) =>
      s.segmentIndex === segmentIndex ? { ...s, uploadFailed: true } : s
    );
    this.notifySegmentsChanged();
    if (segment) this.listeners.onUploadFailed?.(segment, result.error);
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
    if (this._retryAttempts.length >= MAX_RETRY_ATTEMPTS) {
      this.transitionTo("paused-failed");
      this.listeners.onRetryFailed?.();
      return;
    }

    const attempt = this._retryAttempts.length;
    const backoff = RETRY_BACKOFF_MS[attempt] ?? RETRY_BACKOFF_MS[RETRY_BACKOFF_MS.length - 1];
    const sessionId = this._sessionId;

    this.cancelRetryTimer();
    this._retryTimer = setTimeout(async () => {
      this._retryTimer = null;
      // Discard / dispose / a fresh start can land between scheduling
      // and firing; bail without touching state if any of those
      // happened.
      if (this._disposed || this._state !== "reconnecting" || this._sessionId !== sessionId) {
        return;
      }
      this._retryAttempts.push({ attempt, startedAt: this._now() });
      const outcome = await this.attemptStartSegment();
      if (this._disposed || this._sessionId !== sessionId) return;
      if (outcome.ok) {
        this._retryAttempts = [];
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

  private notifySegmentsChanged(): void {
    this.listeners.onSegmentsChanged?.(this._segments);
  }

  private extensionForMime(mimeType: string): string {
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

  private recordToSummarySegment = (record: SegmentRecord): SessionSegment => ({
    segmentIndex: record.segmentIndex,
    durationMs: record.durationMs,
    bytes: record.blob.size,
    mimeType: record.mimeType,
    capturedAt: record.capturedAt,
    uploadedFileId: record.uploadedFileId,
    uploadFailed: false
  });
}

export { SESSION_RECOVERY_TTL_MS };
