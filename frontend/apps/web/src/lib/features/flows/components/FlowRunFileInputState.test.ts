import { describe, expect, it } from "vitest";

import type { UploadedFile } from "@eneo/eneo-js";
import { buildSegmentFilenameBase } from "$lib/features/audio/recordingSession";
import type { SegmentRecord, SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
import { FlowRunFileInputState } from "./FlowRunFileInputState.svelte";

const snapshot = {
  publishedFlowVersion: 1,
  maxFiles: 5,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"],
  inputFormat: "audio"
};

function uploadedFile(id: string): UploadedFile {
  return {
    id,
    name: `${id}.webm`,
    mimetype: "audio/webm",
    size: 128,
    created_at: "2026-05-01T08:00:00.000Z"
  };
}

// An uploaded recorded segment, named the way the recorder names its files.
function uploadedSegment(
  id: string,
  sessionId: string,
  segmentIndex: number,
  capturedAt: number
): UploadedFile {
  return {
    ...uploadedFile(id),
    name: `${buildSegmentFilenameBase(sessionId, segmentIndex, capturedAt)}.webm`
  };
}

function recordingFile(name = "clip.webm"): File {
  return new File([new Blob(["audio"], { type: "audio/webm" })], name, {
    type: "audio/webm"
  });
}

// A recorded segment that arrived and reached the local store.
function persistedSegment(
  state: FlowRunFileInputState,
  stepId: string,
  { notice = null, degraded = false }: { notice?: string | null; degraded?: boolean } = {}
) {
  const segment = state.prepareRecordedSegment(stepId);
  state.recordedSegmentArrived(stepId, segment, recordingFile(`seg${segment.segmentIndex}.webm`));
  state.recordSegmentPersistence({ stepId, segment, notice, degraded });
  return segment;
}

function segmentRecord(segmentIndex: number, uploadedFileId: string | null): SegmentRecord {
  return {
    flowId: "flow-1",
    stepId: "step-a",
    sessionId: "session-a",
    segmentIndex,
    blob: new Blob(["audio"], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 1_000,
    capturedAt: Date.UTC(2026, 4, 1, 8, segmentIndex),
    uploadedFileId,
    reason: "rotation",
    contractSnapshot: snapshot
  };
}

function recoveryHint(stepId: string, sessionId: string): SessionRecoveryHint {
  return {
    flowId: "flow-1",
    stepId,
    sessionId,
    segmentCount: 2,
    totalDurationMs: 20_000,
    earliestCapturedAt: Date.UTC(2026, 4, 1, 8, 0, 0),
    uploadedCount: 1,
    contractSnapshot: snapshot
  };
}

describe("FlowRunFileInputState", () => {
  it("starts with stable defaults for unknown steps", () => {
    const state = new FlowRunFileInputState();

    expect(state.getUploadedFiles("missing")).toEqual([]);
    expect(state.segmentsAwaitingUpload("missing")).toBe(0);
    expect(state.failedRecordedSegments("missing")).toEqual([]);
    expect(state.getRecorderResetToken("missing")).toBe(0);
    expect(state.getUploadError("missing")).toBeNull();
    expect(state.getRecordingNotice("missing")).toBeNull();
    expect(state.getSkippedMessage("missing")).toBeNull();
    expect(state.getResumeHint("missing")).toBeNull();
    expect(state.isStepUploading("missing")).toBe(false);
    expect(state.isStepRecording("missing")).toBe(false);
    expect(state.isDraggingStep("missing")).toBe(false);
    expect(state.isResumeBusyForStep("missing")).toBe(false);
    expect(state.isResumePromptForStep("missing")).toBe(false);
    expect(state.getSessionPhase("missing")).toBe("idle");
  });

  it("keeps uploaded files scoped by step and clears related notices on removal", () => {
    const state = new FlowRunFileInputState();
    state.recordUploadedFile("step-a", uploadedFile("file-a"));
    state.recordUploadedFile("step-b", uploadedFile("file-b"));
    state.recordSkippedFiles("step-a", "too many files");
    persistedSegment(state, "step-a", { notice: "recording stopped" });

    const session = state.removeUploadedFile("step-a", "file-a");

    expect(session).toBe(state.sessionIdsByStepIdSnapshot["step-a"]);
    expect(state.getUploadedFiles("step-a")).toEqual([]);
    expect(state.getUploadedFiles("step-b")).toEqual([uploadedFile("file-b")]);
    expect(state.getRecordingNotice("step-a")).toBeNull();
    expect(state.getSkippedMessage("step-a")).toBeNull();
  });

  it("tracks concurrent uploads independently across steps", () => {
    const state = new FlowRunFileInputState();
    state.recordUploadFailure("step-a", "old error");
    state.recordSkippedFiles("step-a", "old skipped");

    state.retryRequested("step-a");
    expect(state.getUploadError("step-a")).toBeNull();

    state.beginStepUpload("step-a");
    state.beginStepUpload("step-b");
    state.finishStepUpload("step-a");

    expect(state.isStepUploading("step-a")).toBe(false);
    expect(state.isStepUploading("step-b")).toBe(true);
    expect(state.uploadingStepIdsSnapshot).toEqual(["step-b"]);
    expect(state.getUploadError("step-a")).toBeNull();
    expect(state.getSkippedMessage("step-a")).toBeNull();
  });

  it("submits a step's recorded segments in capture order whatever order they upload in", () => {
    const state = new FlowRunFileInputState();
    // Session ids that sort opposite to their capture times.
    const later = "0a1b2c3d-0000-4000-8000-000000000001";
    const earlier = "0f1b2c3d-0000-4000-8000-000000000002";
    const at = (hour: number, minute: number) => Date.UTC(2026, 4, 1, hour, minute);

    state.recordUploadedFile("step-a", uploadedFile("notes"));
    state.recordUploadedFile("step-a", uploadedSegment("later-1", later, 1, at(10, 20)));
    state.recordUploadedFile("step-a", uploadedSegment("earlier-0", earlier, 0, at(9, 0)));
    state.recordUploadedFile("step-a", uploadedFile("slides"));
    state.recordUploadedFile("step-a", uploadedSegment("later-0", later, 0, at(10, 0)));

    // Segments take the segment slots in capture order; the other files keep
    // their places. The run is submitted in this order.
    const inCaptureOrder = ["notes", "earlier-0", "later-0", "slides", "later-1"];
    expect(state.getUploadedFiles("step-a").map(({ id }) => id)).toEqual(inCaptureOrder);
    expect(state.runtimeFilesSnapshot["step-a"]?.map(({ id }) => id)).toEqual(inCaptureOrder);

    // Within a session, the segment index breaks a tie in capture time.
    const tied = new FlowRunFileInputState();
    tied.recordUploadedFile("step-a", uploadedSegment("tie-1", later, 1, at(11, 0)));
    tied.recordUploadedFile("step-a", uploadedSegment("tie-0", later, 0, at(11, 0)));
    expect(tied.runtimeFilesSnapshot["step-a"]?.map(({ id }) => id)).toEqual(["tie-0", "tie-1"]);
  });

  it("keeps a step active until all of its uploads finish", () => {
    const state = new FlowRunFileInputState();

    state.beginStepUpload("step-a");
    state.beginStepUpload("step-a");
    state.finishStepUpload("step-a");

    expect(state.isStepUploading("step-a")).toBe(true);
    expect(state.uploadingStepIdsSnapshot).toEqual(["step-a"]);

    state.finishStepUpload("step-a");

    expect(state.isStepUploading("step-a")).toBe(false);
    expect(state.uploadingStepIdsSnapshot).toEqual([]);
  });

  it("preserves recorded files and discards a step as one state transition", () => {
    const state = new FlowRunFileInputState();
    const prepared = persistedSegment(state, "step-a", {
      notice: "saved after error",
      degraded: true
    });
    state.recordedSegmentFailed("step-a", prepared);
    state.recordUploadedFile("step-a", uploadedFile("file-a"));
    state.recordUploadedFile("step-b", uploadedFile("file-b"));
    state.recordUploadFailure("step-a", "upload failed");
    state.recordUploadFailure("step-b", "step b error");
    state.recordSkippedFiles("step-a", "skipped");
    state.recordingStarted("step-a");
    state.syncSessionPhase("step-a", "paused-failed");

    state.discardStepRecording("step-a");

    expect(prepared.segmentIndex).toBe(0);
    expect(state.failedRecordedSegments("step-a")).toEqual([]);
    expect(state.localRecordingStepIds).toEqual([]);
    expect(state.getRecorderResetToken("step-a")).toBe(1);
    expect(state.getUploadError("step-a")).toBeNull();
    expect(state.getRecordingNotice("step-a")).toBeNull();
    expect(state.getSkippedMessage("step-a")).toBeNull();
    expect(state.getUploadedFiles("step-a")).toEqual([]);
    expect(state.getUploadedFiles("step-b")).toEqual([uploadedFile("file-b")]);
    expect(state.getUploadError("step-b")).toBe("step b error");
    expect(state.isStepRecording("step-a")).toBe(false);
    expect(state.getSessionPhase("step-a")).toBe("idle");
    expect(state.sessionIdsByStepIdSnapshot).toEqual({});
    expect(state.segmentsAwaitingUpload("step-a")).toBe(0);
    expect(state.isStorageDegraded).toBe(true);
  });

  it("prepares recorded segment counters per step", () => {
    const state = new FlowRunFileInputState();

    const firstA = state.prepareRecordedSegment("step-a");
    const secondA = state.prepareRecordedSegment("step-a");
    const firstB = state.prepareRecordedSegment("step-b");

    expect(firstA.sessionId).toBe(secondA.sessionId);
    expect(firstA.segmentIndex).toBe(0);
    expect(secondA.segmentIndex).toBe(1);
    expect(firstB.segmentIndex).toBe(0);
    expect(firstB.sessionId).not.toBe(firstA.sessionId);
  });

  it("tracks each recorded segment from its arrival until its own upload succeeds", () => {
    const state = new FlowRunFileInputState();
    const first = state.prepareRecordedSegment("step-a");
    const second = state.prepareRecordedSegment("step-a");
    state.recordedSegmentArrived("step-a", first, recordingFile("first.webm"));
    state.recordedSegmentArrived("step-a", second, recordingFile("second.webm"));

    // Counted and blocking the run while still being written to the store.
    expect(state.segmentsAwaitingUpload("step-a")).toBe(2);
    expect(state.hasPersistingRecordedSegments).toBe(true);
    expect(state.localRecordingStepIds).toEqual(["step-a"]);

    for (const segment of [first, second]) {
      state.recordSegmentPersistence({
        stepId: "step-a",
        segment,
        notice: "upload pending",
        degraded: false
      });
    }
    expect(state.hasPersistingRecordedSegments).toBe(false);

    // The earlier upload fails and the later one succeeds: only the later one leaves.
    state.recordedSegmentFailed("step-a", first);
    state.recordedSegmentUploaded("step-a", second);
    expect(state.segmentsAwaitingUpload("step-a")).toBe(1);
    expect(state.failedRecordedSegments("step-a").map(({ file }) => file.name)).toEqual([
      "first.webm"
    ]);
    expect(state.localRecordingStepIds).toEqual(["step-a"]);

    state.recordedSegmentUploading("step-a", first);
    expect(state.failedRecordedSegments("step-a")).toEqual([]);
    state.recordedSegmentUploaded("step-a", first);
    expect(state.segmentsAwaitingUpload("step-a")).toBe(0);
    expect(state.localRecordingStepIds).toEqual([]);
    expect(state.getRecorderResetToken("step-a")).toBe(0);
    expect(state.getRecordingNotice("step-a")).toBe("upload pending");
  });

  it("tracks recovered segments that still need an upload and numbers new ones after them", () => {
    const state = new FlowRunFileInputState();

    // Segment 1 was removed before the session was saved, leaving a gap.
    state.attachRecoveredSession("step-a", "session-a", [
      segmentRecord(0, "file-0"),
      segmentRecord(2, null)
    ]);

    expect(state.segmentsAwaitingUpload("step-a")).toBe(1);
    expect(state.hasPersistingRecordedSegments).toBe(false);
    expect(state.prepareRecordedSegment("step-a")).toEqual({
      sessionId: "session-a",
      segmentIndex: 3
    });
    state.recordedSegmentFailed("step-a", { sessionId: "session-a", segmentIndex: 2 });
    expect(state.failedRecordedSegments("step-a").map(({ segmentIndex }) => segmentIndex)).toEqual([
      2
    ]);
  });

  it("owns recoverable-session prompt, attach, discard, and busy transitions", () => {
    const state = new FlowRunFileInputState();
    const hintA = recoveryHint("step-a", "session-a");
    const hintB = recoveryHint("step-b", "session-b");

    state.applyResumeScan({ "step-a": [hintA], "step-b": [hintB] }, "step-a");
    expect(state.getResumeHint("step-a")).toBe(hintA);
    expect(state.isResumePromptForStep("step-a")).toBe(true);
    expect(state.beginResumeAction("step-a")).toBe(true);
    expect(state.beginResumeAction("step-b")).toBe(false);
    expect(state.isResumeBusyForStep("step-a")).toBe(true);

    state.attachRecoveredSession("step-a", "session-a", [segmentRecord(0, "file-0")]);
    state.finishResumeAction();

    expect(state.getResumeHint("step-a")).toBeNull();
    expect(state.isResumePromptForStep("step-a")).toBe(false);
    expect(state.isResumeBusyForStep("step-a")).toBe(false);
    expect(state.sessionIdsByStepIdSnapshot).toEqual({ "step-a": "session-a" });

    state.dismissResumePrompt();
    expect(state.isResumePromptForStep("step-a")).toBe(false);

    state.applyResumeScan({ "step-b": [hintB] }, "step-b");
    state.beginResumeAction("step-b");
    state.discardRecoveredSession("step-b");
    state.finishResumeAction();

    expect(state.getResumeHint("step-b")).toBeNull();
    expect(state.isResumePromptForStep("step-b")).toBe(false);
    expect(state.isResumeBusyForStep("step-b")).toBe(false);
  });

  it("resets all in-memory state between dialog opens and after accepted runs", () => {
    const state = new FlowRunFileInputState();
    state.recordUploadedFile("step-a", uploadedFile("file-a"));
    state.beginStepUpload("step-a");
    state.beginStepUpload("step-a");
    state.recordingStarted("step-a");
    state.dragEnteredStep("step-a");
    state.applyResumeScan({ "step-a": [recoveryHint("step-a", "session-a")] }, "step-a");
    persistedSegment(state, "step-a", { notice: "notice", degraded: true });

    state.resetForDialogClose();

    expect(state.getUploadedFiles("step-a")).toEqual([]);
    expect(state.uploadingStepIdsSnapshot).toEqual([]);
    expect(state.hasActiveRecording).toBe(false);
    expect(state.isDraggingStep("step-a")).toBe(false);
    expect(state.getResumeHint("step-a")).toBeNull();
    expect(state.segmentsAwaitingUpload("step-a")).toBe(0);
    expect(state.isStorageDegraded).toBe(false);

    state.recordUploadedFile("step-b", uploadedFile("file-b"));
    state.resetAfterRunAccepted();

    expect(state.runtimeFilesSnapshot).toEqual({});
  });
});
