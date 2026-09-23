import type { UploadedFile } from "@eneo/eneo-js";
import { parseSegmentFilename, type SessionState } from "$lib/features/audio/recordingSession";
import type { SegmentRecord, SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
import {
  bumpSegmentCountInState,
  clearStepSessionInState,
  emptyRecordingSessionState,
  ensureSessionIdInState,
  makeReuploadFileFromRecord,
  type RecordingSessionState
} from "$lib/features/audio/flowRunRecordingSession";

export type FlowRunRecordingSessionPhase = "idle" | "reconnecting" | "paused-failed";

export type PreparedRecordedSegment = {
  sessionId: string;
  segmentIndex: number;
};

export type PendingRecordedSegment = PreparedRecordedSegment & {
  file: File;
  state: "persisting" | "uploading" | "failed";
};

export class FlowRunFileInputState {
  #runtimeFilesByStepId = $state<Record<string, UploadedFile[]>>({});
  // Recorded segments not uploaded yet, in segment order, from arrival until
  // their own upload succeeds. Retry, the upload backlog and the run blockers
  // all read this one collection.
  #pendingSegmentsByStepId = $state<Record<string, PendingRecordedSegment[]>>({});
  #recorderResetTokensByStepId = $state<Record<string, number>>({});
  #uploadErrorsByStepId = $state<Record<string, string | null>>({});
  #recordingNoticesByStepId = $state<Record<string, string | null>>({});
  #skippedMessagesByStepId = $state<Record<string, string | null>>({});
  #activeUploadCountByStepId = $state<Record<string, number>>({});
  #recordingStepIds = $state<string[]>([]);
  #draggingStepId = $state<string | null>(null);
  #recordingSessionState = $state<RecordingSessionState>(emptyRecordingSessionState());
  #sessionPhaseByStepId = $state<Record<string, FlowRunRecordingSessionPhase>>({});

  get runtimeFilesSnapshot(): Record<string, UploadedFile[]> {
    return Object.fromEntries(
      Object.entries(this.#runtimeFilesByStepId).map(([stepId, files]) => [stepId, [...files]])
    );
  }

  get uploadingStepIdsSnapshot(): string[] {
    return Object.keys(this.#activeUploadCountByStepId);
  }

  get recordingStepIdsSnapshot(): string[] {
    return [...this.#recordingStepIds];
  }

  get localRecordingStepIds(): string[] {
    return Object.entries(this.#pendingSegmentsByStepId)
      .filter(([, segments]) => segments.length > 0)
      .map(([stepId]) => stepId);
  }

  get hasLocalRecordedFiles(): boolean {
    return this.localRecordingStepIds.length > 0;
  }

  get hasPersistingRecordedSegments(): boolean {
    return Object.values(this.#pendingSegmentsByStepId).some((segments) =>
      segments.some((segment) => segment.state === "persisting")
    );
  }

  get hasRuntimeFiles(): boolean {
    return Object.values(this.#runtimeFilesByStepId).some((files) => files.length > 0);
  }

  get hasActiveRecording(): boolean {
    return this.#recordingStepIds.length > 0;
  }

  get isStorageDegraded(): boolean {
    return this.#recordingSessionState.storageDegraded;
  }

  get sessionIdsByStepIdSnapshot(): Record<string, string> {
    return { ...this.#recordingSessionState.sessionIdsByStepId };
  }

  getUploadedFiles(stepId: string): UploadedFile[] {
    return [...(this.#runtimeFilesByStepId[stepId] ?? [])];
  }

  isStepUploading(stepId: string): boolean {
    return (this.#activeUploadCountByStepId[stepId] ?? 0) > 0;
  }

  segmentsAwaitingUpload(stepId: string): number {
    return this.#pendingSegmentsByStepId[stepId]?.length ?? 0;
  }

  failedRecordedSegments(stepId: string): PendingRecordedSegment[] {
    return (this.#pendingSegmentsByStepId[stepId] ?? []).filter(
      (segment) => segment.state === "failed"
    );
  }

  isStepRecording(stepId: string): boolean {
    return this.#recordingStepIds.includes(stepId);
  }

  isDraggingStep(stepId: string): boolean {
    return this.#draggingStepId === stepId;
  }

  getRecorderResetToken(stepId: string): number {
    return this.#recorderResetTokensByStepId[stepId] ?? 0;
  }

  getUploadError(stepId: string): string | null {
    return this.#uploadErrorsByStepId[stepId] ?? null;
  }

  getRecordingNotice(stepId: string): string | null {
    return this.#recordingNoticesByStepId[stepId] ?? null;
  }

  getSkippedMessage(stepId: string): string | null {
    return this.#skippedMessagesByStepId[stepId] ?? null;
  }

  getResumeHint(stepId: string): SessionRecoveryHint | null {
    return this.#recordingSessionState.resumeHintsByStepId[stepId]?.[0] ?? null;
  }

  isResumePromptForStep(stepId: string): boolean {
    return this.#recordingSessionState.resumePromptStepId === stepId;
  }

  isResumeBusyForStep(stepId: string): boolean {
    return this.#recordingSessionState.resumeBusyStepId === stepId;
  }

  getSessionPhase(stepId: string): FlowRunRecordingSessionPhase {
    return this.#sessionPhaseByStepId[stepId] ?? "idle";
  }

  beginStepUpload(stepId: string, options: { clearRecordingNotice?: boolean } = {}): void {
    this.#uploadErrorsByStepId = { ...this.#uploadErrorsByStepId, [stepId]: null };
    if (options.clearRecordingNotice ?? true) {
      this.#recordingNoticesByStepId = { ...this.#recordingNoticesByStepId, [stepId]: null };
    }
    this.#skippedMessagesByStepId = { ...this.#skippedMessagesByStepId, [stepId]: null };
    this.#activeUploadCountByStepId = {
      ...this.#activeUploadCountByStepId,
      [stepId]: (this.#activeUploadCountByStepId[stepId] ?? 0) + 1
    };
  }

  recordUploadedFile(stepId: string, file: UploadedFile): void {
    this.#runtimeFilesByStepId = {
      ...this.#runtimeFilesByStepId,
      [stepId]: inSegmentOrder([...(this.#runtimeFilesByStepId[stepId] ?? []), file])
    };
  }

  recordUploadFailure(stepId: string, message: string): void {
    this.#uploadErrorsByStepId = { ...this.#uploadErrorsByStepId, [stepId]: message };
  }

  recordSkippedFiles(stepId: string, message: string): void {
    this.#skippedMessagesByStepId = { ...this.#skippedMessagesByStepId, [stepId]: message };
  }

  retryRequested(stepId: string): void {
    this.#uploadErrorsByStepId = { ...this.#uploadErrorsByStepId, [stepId]: null };
  }

  finishStepUpload(stepId: string): void {
    const activeCount = this.#activeUploadCountByStepId[stepId] ?? 0;
    if (activeCount > 1) {
      this.#activeUploadCountByStepId = {
        ...this.#activeUploadCountByStepId,
        [stepId]: activeCount - 1
      };
      return;
    }
    if (activeCount === 0) return;
    const next = { ...this.#activeUploadCountByStepId };
    delete next[stepId];
    this.#activeUploadCountByStepId = next;
  }

  removeUploadedFile(stepId: string, fileId: string): string | null {
    this.#runtimeFilesByStepId = {
      ...this.#runtimeFilesByStepId,
      [stepId]: (this.#runtimeFilesByStepId[stepId] ?? []).filter((file) => file.id !== fileId)
    };
    this.#recordingNoticesByStepId = { ...this.#recordingNoticesByStepId, [stepId]: null };
    this.#skippedMessagesByStepId = { ...this.#skippedMessagesByStepId, [stepId]: null };
    return this.#recordingSessionState.sessionIdsByStepId[stepId] ?? null;
  }

  dragEnteredStep(stepId: string): void {
    this.#draggingStepId = stepId;
  }

  dragLeftStep(stepId: string): void {
    if (this.#draggingStepId === stepId) {
      this.#draggingStepId = null;
    }
  }

  clearDrag(): void {
    this.#draggingStepId = null;
  }

  recordingStarted(stepId: string): void {
    this.#recordingStepIds = addUnique(this.#recordingStepIds, stepId);
  }

  recordingStopped(stepId: string): void {
    this.#recordingStepIds = this.#recordingStepIds.filter((id) => id !== stepId);
  }

  prepareRecordedSegment(stepId: string): PreparedRecordedSegment {
    const ensured = ensureSessionIdInState(this.#recordingSessionState.sessionIdsByStepId, stepId);
    const bumped = bumpSegmentCountInState(
      this.#recordingSessionState.segmentCountsByStepId,
      stepId
    );
    this.#recordingSessionState = {
      ...this.#recordingSessionState,
      sessionIdsByStepId: ensured.sessionIdsByStepId,
      segmentCountsByStepId: bumped.segmentCountsByStepId
    };
    return { sessionId: ensured.sessionId, segmentIndex: bumped.segmentIndex };
  }

  // Reserved as the segment arrives, before it is written to the local store,
  // so it already counts toward the backlog and blocks the run.
  recordedSegmentArrived(stepId: string, segment: PreparedRecordedSegment, file: File): void {
    this.#setPendingSegments(stepId, [
      ...(this.#pendingSegmentsByStepId[stepId] ?? []),
      { ...segment, file, state: "persisting" }
    ]);
  }

  recordSegmentPersistence({
    stepId,
    segment,
    notice,
    degraded
  }: {
    stepId: string;
    segment: PreparedRecordedSegment;
    notice: string | null;
    degraded: boolean;
  }): void {
    if (degraded) {
      this.#recordingSessionState = { ...this.#recordingSessionState, storageDegraded: true };
    }
    this.#recordingNoticesByStepId = { ...this.#recordingNoticesByStepId, [stepId]: notice };
    this.#setPendingSegmentState(stepId, segment, "uploading");
  }

  recordedSegmentUploading(stepId: string, segment: PreparedRecordedSegment): void {
    this.#setPendingSegmentState(stepId, segment, "uploading");
  }

  recordedSegmentFailed(stepId: string, segment: PreparedRecordedSegment): void {
    this.#setPendingSegmentState(stepId, segment, "failed");
  }

  recordedSegmentUploaded(stepId: string, segment: PreparedRecordedSegment): void {
    this.#setPendingSegments(
      stepId,
      (this.#pendingSegmentsByStepId[stepId] ?? []).filter(
        (pending) => !isSegment(pending, segment)
      )
    );
  }

  discardStepRecording(stepId: string): void {
    this.#setPendingSegments(stepId, []);
    this.#recorderResetTokensByStepId = {
      ...this.#recorderResetTokensByStepId,
      [stepId]: (this.#recorderResetTokensByStepId[stepId] ?? 0) + 1
    };
    this.#uploadErrorsByStepId = { ...this.#uploadErrorsByStepId, [stepId]: null };
    this.#recordingNoticesByStepId = { ...this.#recordingNoticesByStepId, [stepId]: null };
    this.#skippedMessagesByStepId = { ...this.#skippedMessagesByStepId, [stepId]: null };
    this.#runtimeFilesByStepId = { ...this.#runtimeFilesByStepId, [stepId]: [] };
    this.#recordingStepIds = this.#recordingStepIds.filter((id) => id !== stepId);
    this.#recordingSessionState = clearStepSessionInState(this.#recordingSessionState, stepId);
    this.forgetSessionPhase(stepId);
  }

  beginResumeAction(stepId: string): boolean {
    if (this.#recordingSessionState.resumeBusyStepId !== null) return false;
    this.#recordingSessionState = { ...this.#recordingSessionState, resumeBusyStepId: stepId };
    return true;
  }

  finishResumeAction(): void {
    this.#recordingSessionState = { ...this.#recordingSessionState, resumeBusyStepId: null };
  }

  applyResumeScan(hints: Record<string, SessionRecoveryHint[]>, promptStepId: string | null): void {
    this.#recordingSessionState = {
      ...this.#recordingSessionState,
      resumeHintsByStepId: hints,
      resumePromptStepId: promptStepId
    };
  }

  // Recovered segments without an upload join the pending ones. New segments
  // continue after the highest recovered index: a removed segment leaves a
  // gap, and reusing an index would overwrite that record in the store.
  attachRecoveredSession(stepId: string, sessionId: string, records: SegmentRecord[]): void {
    this.#setPendingSegments(stepId, [
      ...(this.#pendingSegmentsByStepId[stepId] ?? []),
      ...records
        .filter((record) => !record.uploadedFileId)
        .map((record) => ({
          sessionId: record.sessionId,
          segmentIndex: record.segmentIndex,
          file: makeReuploadFileFromRecord(record),
          state: "uploading" as const
        }))
    ]);
    this.#recordingSessionState = {
      ...this.#recordingSessionState,
      sessionIdsByStepId: {
        ...this.#recordingSessionState.sessionIdsByStepId,
        [stepId]: sessionId
      },
      segmentCountsByStepId: {
        ...this.#recordingSessionState.segmentCountsByStepId,
        [stepId]: Math.max(-1, ...records.map((record) => record.segmentIndex)) + 1
      },
      resumeHintsByStepId: {
        ...this.#recordingSessionState.resumeHintsByStepId,
        [stepId]: []
      },
      resumePromptStepId: null
    };
  }

  discardRecoveredSession(stepId: string): void {
    this.#recordingSessionState = {
      ...this.#recordingSessionState,
      resumeHintsByStepId: {
        ...this.#recordingSessionState.resumeHintsByStepId,
        [stepId]: []
      },
      resumePromptStepId: null
    };
  }

  dismissResumePrompt(): void {
    this.#recordingSessionState = { ...this.#recordingSessionState, resumePromptStepId: null };
  }

  syncSessionPhase(stepId: string, recordingState: SessionState): void {
    if (recordingState === "reconnecting" || recordingState === "paused-failed") {
      this.#sessionPhaseByStepId = { ...this.#sessionPhaseByStepId, [stepId]: recordingState };
      return;
    }
    this.forgetSessionPhase(stepId);
  }

  forgetSessionPhase(stepId: string): void {
    if (!(stepId in this.#sessionPhaseByStepId)) return;
    const next = { ...this.#sessionPhaseByStepId };
    delete next[stepId];
    this.#sessionPhaseByStepId = next;
  }

  resetForDialogClose(): void {
    this.#reset();
  }

  resetAfterRunAccepted(): void {
    this.#reset();
  }

  #reset(): void {
    this.#runtimeFilesByStepId = {};
    this.#pendingSegmentsByStepId = {};
    this.#recorderResetTokensByStepId = {};
    this.#uploadErrorsByStepId = {};
    this.#recordingNoticesByStepId = {};
    this.#skippedMessagesByStepId = {};
    this.#activeUploadCountByStepId = {};
    this.#recordingStepIds = [];
    this.#draggingStepId = null;
    this.#recordingSessionState = emptyRecordingSessionState();
    this.#sessionPhaseByStepId = {};
  }

  #setPendingSegmentState(
    stepId: string,
    segment: PreparedRecordedSegment,
    state: PendingRecordedSegment["state"]
  ): void {
    this.#setPendingSegments(
      stepId,
      (this.#pendingSegmentsByStepId[stepId] ?? []).map((pending) =>
        isSegment(pending, segment) ? { ...pending, state } : pending
      )
    );
  }

  #setPendingSegments(stepId: string, segments: PendingRecordedSegment[]): void {
    this.#pendingSegmentsByStepId = {
      ...this.#pendingSegmentsByStepId,
      [stepId]: segments.toSorted((a, b) => a.segmentIndex - b.segmentIndex)
    };
  }
}

function addUnique(values: string[], value: string): string[] {
  return values.includes(value) ? values : [...values, value];
}

// A step's files go to the run in list order and the backend joins their
// transcripts in that order, so recorded segments take their slots in capture
// order whatever order their uploads finished in (a retried segment must not
// follow a later one); within a session the segment index breaks a tie. Other
// files keep their places.
function inSegmentOrder(files: UploadedFile[]): UploadedFile[] {
  const segments = files.flatMap((file, slot) => {
    const segment = parseSegmentFilename(file.name ?? "");
    return segment ? [{ file, slot, ...segment }] : [];
  });
  const sorted = segments.toSorted(
    (a, b) =>
      a.capturedAt - b.capturedAt ||
      (a.sessionId === b.sessionId ? a.segmentIndex - b.segmentIndex : 0)
  );
  const ordered = [...files];
  segments.forEach(({ slot }, position) => {
    const next = sorted[position];
    if (next) ordered[slot] = next.file;
  });
  return ordered;
}

function isSegment(pending: PreparedRecordedSegment, segment: PreparedRecordedSegment): boolean {
  return pending.sessionId === segment.sessionId && pending.segmentIndex === segment.segmentIndex;
}
