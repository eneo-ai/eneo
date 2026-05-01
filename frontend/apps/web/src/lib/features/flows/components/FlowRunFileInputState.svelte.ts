import type { UploadedFile } from "@intric/intric-js";
import type { SessionState } from "$lib/features/audio/recordingSession";
import type { SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
import {
  bumpSegmentCountInState,
  clearStepSessionInState,
  emptyRecordingSessionState,
  ensureSessionIdInState,
  type RecordingSessionState
} from "$lib/features/audio/flowRunRecordingSession";

export type FlowRunRecordingSessionPhase = "idle" | "reconnecting" | "paused-failed";

export type PreparedRecordedSegment = {
  sessionId: string;
  segmentIndex: number;
};

export class FlowRunFileInputState {
  #runtimeFilesByStepId = $state<Record<string, UploadedFile[]>>({});
  #recordedFilesByStepId = $state<Record<string, File | null>>({});
  #recorderResetTokensByStepId = $state<Record<string, number>>({});
  #uploadErrorsByStepId = $state<Record<string, string | null>>({});
  #recordingNoticesByStepId = $state<Record<string, string | null>>({});
  #skippedMessagesByStepId = $state<Record<string, string | null>>({});
  #uploadingStepIds = $state<string[]>([]);
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
    return [...this.#uploadingStepIds];
  }

  get recordingStepIdsSnapshot(): string[] {
    return [...this.#recordingStepIds];
  }

  get localRecordingStepIds(): string[] {
    return Object.entries(this.#recordedFilesByStepId)
      .filter(([, file]) => file !== null)
      .map(([stepId]) => stepId);
  }

  get hasLocalRecordedFiles(): boolean {
    return this.localRecordingStepIds.length > 0;
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
    return this.#uploadingStepIds.includes(stepId);
  }

  isStepRecording(stepId: string): boolean {
    return this.#recordingStepIds.includes(stepId);
  }

  isDraggingStep(stepId: string): boolean {
    return this.#draggingStepId === stepId;
  }

  getRecordedFile(stepId: string): File | null {
    return this.#recordedFilesByStepId[stepId] ?? null;
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
    this.#uploadingStepIds = addUnique(this.#uploadingStepIds, stepId);
  }

  recordUploadedFile(stepId: string, file: UploadedFile): void {
    this.#runtimeFilesByStepId = {
      ...this.#runtimeFilesByStepId,
      [stepId]: [...(this.#runtimeFilesByStepId[stepId] ?? []), file]
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
    this.#uploadingStepIds = this.#uploadingStepIds.filter((id) => id !== stepId);
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

  recordSegmentPersistence({
    stepId,
    file,
    notice,
    degraded
  }: {
    stepId: string;
    file: File;
    notice: string | null;
    degraded: boolean;
  }): void {
    if (degraded) {
      this.#recordingSessionState = { ...this.#recordingSessionState, storageDegraded: true };
    }
    this.#recordedFilesByStepId = { ...this.#recordedFilesByStepId, [stepId]: file };
    this.#recordingNoticesByStepId = { ...this.#recordingNoticesByStepId, [stepId]: notice };
  }

  clearPreservedRecording(stepId: string): void {
    this.#recordedFilesByStepId = { ...this.#recordedFilesByStepId, [stepId]: null };
  }

  discardStepRecording(stepId: string): void {
    this.#recordedFilesByStepId = { ...this.#recordedFilesByStepId, [stepId]: null };
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

  attachRecoveredSession(stepId: string, sessionId: string, segmentCount: number): void {
    this.#recordingSessionState = {
      ...this.#recordingSessionState,
      sessionIdsByStepId: {
        ...this.#recordingSessionState.sessionIdsByStepId,
        [stepId]: sessionId
      },
      segmentCountsByStepId: {
        ...this.#recordingSessionState.segmentCountsByStepId,
        [stepId]: segmentCount
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
    this.#recordedFilesByStepId = {};
    this.#recorderResetTokensByStepId = {};
    this.#uploadErrorsByStepId = {};
    this.#recordingNoticesByStepId = {};
    this.#skippedMessagesByStepId = {};
    this.#uploadingStepIds = [];
    this.#recordingStepIds = [];
    this.#draggingStepId = null;
    this.#recordingSessionState = emptyRecordingSessionState();
    this.#sessionPhaseByStepId = {};
  }
}

function addUnique(values: string[], value: string): string[] {
  return values.includes(value) ? values : [...values, value];
}
