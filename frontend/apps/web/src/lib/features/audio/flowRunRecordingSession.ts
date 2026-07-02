// FlowRunDialog helpers for segment filenames, persistence, and resume recovery.

import type { FlowRunContractStepInput, Eneo, UploadedFile } from "@eneo/eneo-js";

import type { RecordingStopReason } from "./recordedAudioFile";
import {
  buildSegmentFilenameBase,
  generateSessionId,
  segmentExtensionFromMime
} from "./recordingSession";
import {
  recordingSessionStore,
  type ContractSnapshot,
  type SegmentRecord,
  type SessionRecoveryHint
} from "./recordingSessionStore";

export { segmentExtensionFromMime } from "./recordingSession";

export type RecordingSessionState = {
  sessionIdsByStepId: Record<string, string>;
  segmentCountsByStepId: Record<string, number>;
  resumeHintsByStepId: Record<string, SessionRecoveryHint[]>;
  resumePromptStepId: string | null;
  resumeBusyStepId: string | null;
  storageDegraded: boolean;
};

export function emptyRecordingSessionState(): RecordingSessionState {
  return {
    sessionIdsByStepId: {},
    segmentCountsByStepId: {},
    resumeHintsByStepId: {},
    resumePromptStepId: null,
    resumeBusyStepId: null,
    storageDegraded: false
  };
}

export function buildContractSnapshotFromStep(
  step: FlowRunContractStepInput,
  publishedFlowVersion: number | null
): ContractSnapshot {
  return {
    publishedFlowVersion,
    maxFiles: step.max_files ?? null,
    maxFileSizeBytes: step.max_file_size_bytes ?? null,
    acceptedMimetypes: [...(step.accepted_mimetypes ?? [])],
    inputFormat: step.input_format ?? null
  };
}

export function composeSegmentFilename(record: SegmentRecord): string {
  return `${buildSegmentFilenameBase(
    record.sessionId,
    record.segmentIndex,
    record.capturedAt
  )}.${segmentExtensionFromMime(record.mimeType)}`;
}

// Synthesizes an UploadedFile pill from an IDB record. We only have the
// server-side file_id; the rest of the metadata is reconstructed from
// the persisted segment so the dialog can render the file in its list
// without an extra round-trip to the backend.
export function synthesizeUploadedFileFromRecord(record: SegmentRecord): UploadedFile {
  if (!record.uploadedFileId) {
    throw new Error("synthesizeUploadedFileFromRecord requires an uploaded record");
  }
  return {
    id: record.uploadedFileId,
    name: composeSegmentFilename(record),
    mimetype: record.mimeType,
    size: record.blob.size,
    created_at: new Date(record.capturedAt).toISOString()
  } as UploadedFile;
}

export function makeReuploadFileFromRecord(record: SegmentRecord): File {
  return new File([record.blob], composeSegmentFilename(record), {
    type: record.mimeType
  });
}

export type EnsureSessionResult = {
  sessionIdsByStepId: Record<string, string>;
  sessionId: string;
};

export function ensureSessionIdInState(
  sessionIdsByStepId: Record<string, string>,
  stepId: string
): EnsureSessionResult {
  const existing = sessionIdsByStepId[stepId];
  if (existing) return { sessionIdsByStepId, sessionId: existing };
  const fresh = generateSessionId();
  return {
    sessionIdsByStepId: { ...sessionIdsByStepId, [stepId]: fresh },
    sessionId: fresh
  };
}

export type BumpSegmentCountResult = {
  segmentCountsByStepId: Record<string, number>;
  segmentIndex: number;
};

export function bumpSegmentCountInState(
  segmentCountsByStepId: Record<string, number>,
  stepId: string
): BumpSegmentCountResult {
  const current = segmentCountsByStepId[stepId] ?? 0;
  return {
    segmentCountsByStepId: {
      ...segmentCountsByStepId,
      [stepId]: current + 1
    },
    segmentIndex: current
  };
}

export function clearStepSessionInState(
  state: RecordingSessionState,
  stepId: string
): RecordingSessionState {
  const next: RecordingSessionState = {
    ...state,
    sessionIdsByStepId: { ...state.sessionIdsByStepId },
    segmentCountsByStepId: { ...state.segmentCountsByStepId },
    resumeHintsByStepId: { ...state.resumeHintsByStepId }
  };
  delete next.sessionIdsByStepId[stepId];
  delete next.segmentCountsByStepId[stepId];
  delete next.resumeHintsByStepId[stepId];
  if (next.resumePromptStepId === stepId) next.resumePromptStepId = null;
  if (next.resumeBusyStepId === stepId) next.resumeBusyStepId = null;
  return next;
}

export type PersistSegmentArgs = {
  flowId: string;
  stepId: string;
  sessionId: string;
  segmentIndex: number;
  blob: Blob;
  mimeType: string;
  reason: RecordingStopReason;
  // Captured at the recorder's stop event. Stored verbatim so the resume
  // prompt can show "X part(s) saved · 1 h 12 min" without having to read
  // every blob to compute the duration.
  durationMs: number;
  capturedAt: number;
  contractSnapshot: ContractSnapshot;
};

export async function persistRecordingSegment(args: PersistSegmentArgs): Promise<{
  degraded: boolean;
}> {
  try {
    const result = await recordingSessionStore.writeSegment({
      flowId: args.flowId,
      stepId: args.stepId,
      sessionId: args.sessionId,
      segmentIndex: args.segmentIndex,
      blob: args.blob,
      mimeType: args.mimeType,
      durationMs: Number.isFinite(args.durationMs) ? Math.max(0, args.durationMs) : 0,
      capturedAt: args.capturedAt,
      uploadedFileId: null,
      reason: args.reason,
      contractSnapshot: args.contractSnapshot
    });
    return { degraded: result.mode === "memory" };
  } catch (error) {
    console.warn("flowRunRecordingSession.persistRecordingSegment: store write failed", error);
    return { degraded: true };
  }
}

export async function markSegmentUploaded(args: {
  flowId: string;
  stepId: string;
  sessionId: string;
  segmentIndex: number;
  uploadedFileId: string;
}): Promise<void> {
  try {
    await recordingSessionStore.patchUploadedFileId(
      args.flowId,
      args.stepId,
      args.sessionId,
      args.segmentIndex,
      args.uploadedFileId
    );
  } catch (error) {
    console.warn("flowRunRecordingSession.markSegmentUploaded failed", error);
  }
}

export async function scanRecoverableSessionsForSteps(args: {
  flowId: string;
  steps: ReadonlyArray<FlowRunContractStepInput>;
}): Promise<Record<string, SessionRecoveryHint[]>> {
  const collected: Record<string, SessionRecoveryHint[]> = {};
  for (const step of args.steps) {
    try {
      const list = await recordingSessionStore.listRecoverableSessions(args.flowId, step.step_id);
      if (list.length > 0) collected[step.step_id] = list;
    } catch (error) {
      console.warn("flowRunRecordingSession: listRecoverableSessions failed", {
        stepId: step.step_id,
        error
      });
    }
  }
  return collected;
}

// Best-effort: deletes server-side files for every uploaded segment of
// this session, then drops the IDB ledger. Errors are logged but do
// not abort — the orphan janitor sweeps any survivors within 24 h, so
// individual delete failures are not load-bearing.
export async function purgeSession(args: {
  eneo: Eneo;
  flowId: string;
  stepId: string;
  sessionId: string;
}): Promise<void> {
  try {
    const records = await recordingSessionStore.readSession(
      args.flowId,
      args.stepId,
      args.sessionId
    );
    for (const record of records) {
      if (record.uploadedFileId) {
        try {
          await args.eneo.files.delete({ fileId: record.uploadedFileId });
        } catch (error) {
          console.warn("flowRunRecordingSession.purgeSession: server file delete failed", {
            fileId: record.uploadedFileId,
            error
          });
        }
      }
    }
    await recordingSessionStore.deleteSession(args.flowId, args.stepId, args.sessionId);
  } catch (error) {
    console.warn("flowRunRecordingSession.purgeSession failed", error);
  }
}

export async function purgeAllSessions(args: {
  flowId: string;
  sessionIdsByStepId: Record<string, string>;
}): Promise<void> {
  for (const [stepId, sessionId] of Object.entries(args.sessionIdsByStepId)) {
    try {
      await recordingSessionStore.deleteSession(args.flowId, stepId, sessionId);
    } catch (error) {
      console.warn("flowRunRecordingSession.purgeAllSessions: session cleanup failed", {
        stepId,
        error
      });
    }
  }
}

export async function readSessionRecords(
  flowId: string,
  stepId: string,
  sessionId: string
): Promise<SegmentRecord[]> {
  return recordingSessionStore.readSession(flowId, stepId, sessionId);
}

// Removes the IDB record whose uploadedFileId matches. Called when the
// user removes a segment from the dialog list, so resume cannot
// reattach the deleted audio later.
export async function detachUploadedSegmentFromLedger(args: {
  flowId: string;
  stepId: string;
  sessionId: string;
  uploadedFileId: string;
}): Promise<void> {
  try {
    await recordingSessionStore.detachUploadedFileId(
      args.flowId,
      args.stepId,
      args.sessionId,
      args.uploadedFileId
    );
  } catch (error) {
    console.warn("flowRunRecordingSession.detachUploadedSegmentFromLedger failed", error);
  }
}
