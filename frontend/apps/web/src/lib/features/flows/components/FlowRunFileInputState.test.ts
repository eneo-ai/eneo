import { describe, expect, it } from "vitest";

import type { UploadedFile } from "@eneo/eneo-js";
import type { SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
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

function recordingFile(name = "clip.webm"): File {
  return new File([new Blob(["audio"], { type: "audio/webm" })], name, {
    type: "audio/webm"
  });
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
    expect(state.getRecordedFile("missing")).toBeNull();
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
    state.prepareRecordedSegment("step-a");
    state.recordSegmentPersistence({
      stepId: "step-a",
      file: recordingFile(),
      notice: "recording stopped",
      degraded: false
    });

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
    const prepared = state.prepareRecordedSegment("step-a");
    state.recordUploadedFile("step-a", uploadedFile("file-a"));
    state.recordUploadedFile("step-b", uploadedFile("file-b"));
    state.recordUploadFailure("step-a", "upload failed");
    state.recordUploadFailure("step-b", "step b error");
    state.recordSkippedFiles("step-a", "skipped");
    state.recordingStarted("step-a");
    state.syncSessionPhase("step-a", "paused-failed");
    state.recordSegmentPersistence({
      stepId: "step-a",
      file: recordingFile(),
      notice: "saved after error",
      degraded: true
    });

    state.discardStepRecording("step-a");

    expect(prepared.segmentIndex).toBe(0);
    expect(state.getRecordedFile("step-a")).toBeNull();
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

  it("clears a preserved recording after successful upload without resetting the recorder", () => {
    const state = new FlowRunFileInputState();
    state.recordSegmentPersistence({
      stepId: "step-a",
      file: recordingFile(),
      notice: "upload pending",
      degraded: false
    });

    state.clearPreservedRecording("step-a");

    expect(state.getRecordedFile("step-a")).toBeNull();
    expect(state.getRecorderResetToken("step-a")).toBe(0);
    expect(state.getRecordingNotice("step-a")).toBe("upload pending");
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

    state.attachRecoveredSession("step-a", "session-a", 3);
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
    state.recordSegmentPersistence({
      stepId: "step-a",
      file: recordingFile(),
      notice: "notice",
      degraded: true
    });

    state.resetForDialogClose();

    expect(state.getUploadedFiles("step-a")).toEqual([]);
    expect(state.uploadingStepIdsSnapshot).toEqual([]);
    expect(state.hasActiveRecording).toBe(false);
    expect(state.isDraggingStep("step-a")).toBe(false);
    expect(state.getResumeHint("step-a")).toBeNull();
    expect(state.getRecordedFile("step-a")).toBeNull();
    expect(state.isStorageDegraded).toBe(false);

    state.recordUploadedFile("step-b", uploadedFile("file-b"));
    state.resetAfterRunAccepted();

    expect(state.runtimeFilesSnapshot).toEqual({});
  });
});
