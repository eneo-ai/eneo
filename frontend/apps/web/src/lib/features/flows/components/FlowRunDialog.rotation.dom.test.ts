import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import type {
  Eneo,
  Flow,
  FlowLiveTranscriptionSession,
  FlowRunContract,
  FlowRunContractStepInput,
  FlowRunContractTranscription,
  UploadedFile
} from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  markSegmentUploaded,
  persistRecordingSegment,
  purgeSession,
  readSessionRecords,
  scanRecoverableSessionsForSteps
} from "$lib/features/audio/flowRunRecordingSession";
import { AUDIO_GRAPH_PREPARATION_MS } from "$lib/features/audio/AudioRecorder.svelte";
import { FINAL_TEXT_WAIT_MS } from "$lib/features/audio/live/LiveTranscriptPreview.svelte";
import {
  FakeLiveSocket,
  FakeWorkletNode,
  frameTags,
  installLiveTranscriptFakes,
  liveSession
} from "$lib/features/audio/live/liveTranscriptTestFakes";
import { PCM16_FLUSH, PCM16_FLUSHED } from "$lib/features/audio/live/pcm16-worklet.js";
import {
  RETRY_BACKOFF_MS,
  ROTATION_OVERLAP_MS,
  SEGMENT_ROTATION_MS
} from "$lib/features/audio/recordingSession";
import type { SegmentRecord, SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
import { toast } from "$lib/components/toast";
import { m } from "$lib/paraglide/messages";
import FlowRunDialog from "./FlowRunDialog.svelte";

// Drives the real AudioRecorder and RecordingSession through the dialog, with
// the browser's media APIs replaced by the fakes below.

const recordingMocks = vi.hoisted(() => ({
  markSegmentUploaded: vi.fn(async () => undefined),
  persistRecordingSegment: vi.fn(async () => ({ degraded: false })),
  purgeSession: vi.fn(async () => undefined),
  readSessionRecords: vi.fn(async () => []),
  scanRecoverableSessionsForSteps: vi.fn(async () => ({}))
}));

vi.mock("$lib/features/audio/flowRunRecordingSession", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("$lib/features/audio/flowRunRecordingSession")>();
  return { ...actual, ...recordingMocks };
});

vi.mock("@eneo/eneo-js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/eneo-js")>();
  return {
    ...actual,
    createFlowRuntimeUploadTimeoutController: () => ({
      onProgress: () => undefined,
      clear: () => undefined
    })
  };
});

vi.mock("$lib/components/toast", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn()
  }
}));

// performance.now and requestAnimationFrame stay real so the stall watchdog
// and the level meter see a healthy microphone while hours of fake time pass.
const FAKED_CLOCK = ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] as const;
const LOCAL_RECORDING_BLOCKER =
  "Slutför uppladdningen eller kassera inspelningen för steg 1: Audio input.";
const DISCARD_BUSY_REASON =
  "Du kan kassera inspelningen när den har stoppats och uppladdningen är klar.";

let media: ReturnType<typeof installFakeMedia>;

beforeEach(() => {
  media = installFakeMedia();
  vi.mocked(markSegmentUploaded).mockReset().mockResolvedValue(undefined);
  vi.mocked(persistRecordingSegment).mockReset().mockResolvedValue({ degraded: false });
  vi.mocked(purgeSession).mockReset().mockResolvedValue(undefined);
  vi.mocked(readSessionRecords).mockReset().mockResolvedValue([]);
  vi.mocked(scanRecoverableSessionsForSteps).mockReset().mockResolvedValue({});
});

afterEach(async () => {
  vi.useFakeTimers();
  cleanup();
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  // Bits UI releases its body scroll lock after dialog teardown completes.
  await waitFor(() => {
    expect(document.body.style.overflow).not.toBe("hidden");
  });
  media.uninstall();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("FlowRunDialog recording rotation", () => {
  it("records on with the same microphone while the rotated segment's upload is pending", async () => {
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    await openDialogAndStartRecording(upload);

    await rotate();
    // Both recorders capture the stream for the overlap, then the replaced one stops.
    expect(media.recorders).toHaveLength(2);
    expect(media.recorders[0]?.state).toBe("recording");
    vi.advanceTimersByTime(ROTATION_OVERLAP_MS - 1);
    expect(media.recorders[0]?.state).toBe("recording");
    vi.advanceTimersByTime(1);
    expect(media.recorders[0]?.state).toBe("inactive");
    media.recorders[0]?.finish();
    await flush();

    expect(media.recorders[1]?.stream).toBe(media.stream);
    expect(media.recorders[1]?.state).toBe("recording");
    expect(media.track.stop).not.toHaveBeenCalled();
    expect(media.contexts).toHaveLength(1);
    expect(media.contexts[0]?.close).not.toHaveBeenCalled();
    expect(persistedSegments()).toEqual([{ segmentIndex: 0, reason: "rotation" }]);
    expect(upload).toHaveBeenCalledOnce();
    expect(screen.getByLabelText(m.stop_recording())).toBeTruthy();
  });

  it("persists and uploads both segments once when the user stops during the overlap", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(({ file }: { file: File }) => pendingUpload(pendingUploads, file));
    await openDialogAndStartRecording(upload);
    const statesAtRelease = recorderStatesAtRelease();

    await rotate();
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    // The stop ends the overlap at once.
    expect(media.recorders.map(({ state }) => state)).toEqual(["inactive", "inactive"]);
    media.recorders[0]?.finish();
    media.recorders[1]?.finish();
    await flush();
    await endOverlap();

    expect(persistedSegments()).toEqual([
      { segmentIndex: 0, reason: "rotation" },
      { segmentIndex: 1, reason: "manual" }
    ]);
    pendingUploads[0]?.resolve(uploadedFile("segment-0", pendingUploads[0].file.name));
    await flush();
    pendingUploads[1]?.resolve(uploadedFile("segment-1", pendingUploads[1].file.name));
    await flush();

    expect(upload).toHaveBeenCalledTimes(2);
    expect(markedSegments()).toEqual([
      [0, "segment-0"],
      [1, "segment-1"]
    ]);
    expect(screen.getByText(/-seg00-/)).toBeTruthy();
    expect(screen.getByText(/-seg01-/)).toBeTruthy();
    expect(statesAtRelease).toEqual([["inactive", "inactive"]]);
    expect(media.contexts[0]?.close).toHaveBeenCalledOnce();

    // The session ended with the recording, so no rotation reaches the idle recorder.
    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    await flush();
    expect(media.recorders).toHaveLength(2);
    expect(screen.getByLabelText(m.start_recording())).toBeTruthy();
  });

  it("delivers both segments once when the live recorder fails during the overlap", async () => {
    const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile(file.name, file.name));
    await openDialogAndStartRecording(upload);
    const statesAtRelease = recorderStatesAtRelease();

    await rotate();
    media.recorders[1]?.dispatchEvent(new Event("error"));
    expect(media.recorders.map(({ state }) => state)).toEqual(["inactive", "inactive"]);
    media.recorders[0]?.finish();
    media.recorders[1]?.finish();
    await flush();
    await endOverlap();

    expect(persistedSegments()).toEqual([
      { segmentIndex: 0, reason: "rotation" },
      { segmentIndex: 1, reason: "error" }
    ]);
    expect(statesAtRelease).toEqual([["inactive", "inactive"]]);
    expect(screen.getByText(m.recording_session_reconnecting())).toBeTruthy();
  });

  it("delivers both segments once when the dialog is closed during the overlap", async () => {
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    await openDialogAndStartRecording(upload);
    const statesAtRelease = recorderStatesAtRelease();

    await rotate();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await fireEvent.click(screen.getByRole("button", { name: "Stäng ändå" }));
    // Closing stops the recording first, so both segments reach the local store.
    expect(media.recorders.map(({ state }) => state)).toEqual(["inactive", "inactive"]);
    media.recorders[0]?.finish();
    media.recorders[1]?.finish();
    await flush();

    expect(persistedSegments()).toEqual([
      { segmentIndex: 0, reason: "rotation" },
      { segmentIndex: 1, reason: "manual" }
    ]);
    expect(statesAtRelease).toEqual([["inactive", "inactive"]]);
  });

  it("keeps the replaced segment when the recorder unmounts during the overlap", async () => {
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    const { unmount } = await openDialogAndStartRecording(upload);
    const statesAtRelease = recorderStatesAtRelease();

    await rotate();
    unmount();
    media.recorders[0]?.finish();
    media.recorders[1]?.finish();
    await flush();

    // The segment in progress goes with the unmount; the completed one does not.
    expect(persistedSegments()).toEqual([{ segmentIndex: 0, reason: "rotation" }]);
    expect(statesAtRelease).toEqual([["inactive", "inactive"]]);
  });

  it.each(["upload", "persistence"] as const)(
    "stops, and refuses a restart, while three segments wait for their %s",
    async (pendingStage) => {
      if (pendingStage === "persistence") {
        vi.mocked(persistRecordingSegment).mockImplementation(() => new Promise(() => undefined));
      }
      const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
      await openDialogAndStartRecording(upload);

      for (const finished of [0, 1]) {
        await rotate();
        expect(media.recorders).toHaveLength(finished + 2);
        await endOverlap();
        media.recorders[finished]?.finish();
        await flush();
      }
      expect(screen.getByLabelText(m.stop_recording())).toBeTruthy();

      await rotate();
      media.recorders[2]?.finish();
      await flush();

      expect(media.recorders).toHaveLength(3);
      expect(persistedSegments().map(({ reason }) => reason)).toEqual([
        "rotation",
        "rotation",
        "backlog"
      ]);
      expect(screen.getByText(m.recording_stopped_upload_backlog())).toBeTruthy();
      expect(media.track.stop).toHaveBeenCalledOnce();

      const start = screen.getByLabelText(m.start_recording()) as HTMLButtonElement;
      expect(start.disabled).toBe(true);
      await fireEvent.click(start);
      await flush();
      expect(media.recorders).toHaveLength(3);
    }
  );

  it("gives a recording started while the last segment uploads its own rotation schedule", async () => {
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    await openDialogAndStartRecording(upload);

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS / 2);
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[0]?.finish();
    await flush();
    await fireEvent.click(screen.getByLabelText(m.start_recording()));
    await flush();
    expect(media.recorders).toHaveLength(2);

    // The finished recording's schedule would rotate here, halfway into the new one.
    vi.advanceTimersByTime(SEGMENT_ROTATION_MS / 2);
    await flush();
    expect(media.recorders).toHaveLength(2);

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS / 2);
    await flush();
    expect(media.recorders).toHaveLength(3);
    expect(media.recorders[2]?.state).toBe("recording");
  });

  it("keeps the run blocked until Retry uploads an earlier segment, then submits in segment order", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(({ file }: { file: File }) => pendingUpload(pendingUploads, file));
    const create = vi.fn(async () => ({ id: "run-1" }));
    await openDialogAndStartRecording(upload, { create });

    await rotate();
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    pendingUploads[0]?.reject(new Error("Network down"));
    await flush();
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[1]?.finish();
    await flush();
    pendingUploads[1]?.resolve(uploadedFile("segment-1", pendingUploads[1].file.name));
    await flush();

    expect(screen.getByText(/-seg01-/)).toBeTruthy();
    expect(nextButton().disabled).toBe(true);
    expect(screen.getByText(LOCAL_RECORDING_BLOCKER)).toBeTruthy();

    await fireEvent.click(retryInFailedRecordingAlert());
    await flush();
    expect(pendingUploads[2]?.file.name).toMatch(/-seg00-/);
    pendingUploads[2]?.resolve(uploadedFile("segment-0", pendingUploads[2].file.name));
    await flush();

    expect(markedSegments()).toEqual([
      [1, "segment-1"],
      [0, "segment-0"]
    ]);
    expect(failedRecordingAlert()).toBeNull();
    // The retried segment 0 uploaded last but is listed and submitted first.
    expect(screen.getAllByText(/-seg0\d-/).map(({ textContent }) => textContent)).toEqual([
      pendingUploads[2]?.file.name,
      pendingUploads[1]?.file.name
    ]);
    await fireEvent.click(nextButton());
    await flush();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_confirm() }));
    await flush();
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        step_inputs: { "step-audio": { file_ids: ["segment-0", "segment-1"] } }
      })
    );
  });

  it("offers save for later once every segment is handed over and persisted, and discard once none is in flight", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(({ file }: { file: File }) => pendingUpload(pendingUploads, file));
    await openDialogAndStartRecording(upload);

    await rotate();
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    pendingUploads[0]?.reject(new Error("Network down"));
    await flush();

    // Capture continues: Retry is offered, the actions that end the recording are not.
    expect(queryInFailedRecordingAlert("Försök igen")).toBeTruthy();
    expect(queryInFailedRecordingAlert(m.recording_save_for_later())).toBeNull();
    await expectDiscardRefused();

    let finishPersisting = () => {};
    vi.mocked(persistRecordingSegment).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishPersisting = () => resolve({ degraded: false });
        })
    );
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    await flush();
    // Stopped, but the browser has not handed over the last segment yet.
    expect(queryInFailedRecordingAlert(m.recording_save_for_later())).toBeNull();
    await expectDiscardRefused();
    media.recorders[1]?.finish();
    await flush();
    expect(queryInFailedRecordingAlert(m.recording_save_for_later())).toBeNull();

    finishPersisting();
    await flush();
    expect(queryInFailedRecordingAlert(m.recording_save_for_later())).toBeTruthy();
    // The last segment still uploads.
    await expectDiscardRefused();

    pendingUploads[1]?.resolve(uploadedFile("segment-1", pendingUploads[1].file.name));
    await flush();
    expect(screen.getByText(/-seg01-/)).toBeTruthy();
    await fireEvent.click(discardButton());
    await flush();

    expect(purgeSession).toHaveBeenCalledOnce();
    expect(failedRecordingAlert()).toBeNull();
    expect(screen.queryByText(/-seg0\d-/)).toBeNull();
  });

  it("retries when the replacement recorder fails before it captures any audio", async () => {
    const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile("segment-0", file.name));
    await openDialogAndStartRecording(upload);

    await rotate();
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    media.recorders[1]?.dispatchEvent(new Event("error"));
    media.recorders[1]?.finish({ withAudio: false });
    await flush();

    expect(screen.getByText(m.recording_session_reconnecting())).toBeTruthy();
    vi.advanceTimersByTime(RETRY_BACKOFF_MS[0]);
    await flush();
    expect(media.recorders).toHaveLength(3);
    expect(media.recorders[2]?.state).toBe("recording");
    expect(persistedSegments()).toEqual([{ segmentIndex: 0, reason: "rotation" }]);
  });

  it("rotates a recording started again from the paused-failed retry", async () => {
    const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile("segment-0", file.name));
    await openDialogAndStartRecording(upload);

    // Every automatic retry fails, so the session ends in paused-failed.
    RETRY_BACKOFF_MS.forEach(() =>
      media.getUserMedia.mockRejectedValueOnce(new Error("Microphone busy"))
    );
    media.recorders[0]?.dispatchEvent(new Event("error"));
    media.recorders[0]?.finish();
    await flush();
    for (const backoff of RETRY_BACKOFF_MS) {
      vi.advanceTimersByTime(backoff);
      await flush();
    }
    await fireEvent.click(screen.getByRole("button", { name: m.recording_session_paused_retry() }));
    await flush();
    expect(media.recorders).toHaveLength(2);

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    await flush();
    expect(media.recorders).toHaveLength(3);
    expect(media.recorders[2]?.state).toBe("recording");
  });

  it("keeps the dialog on a recording step until capture stops and the segment is persisted", async () => {
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    renderDialog(upload, { steps: [firstAudioStep, { ...audioStep, step_order: 2 }] });
    await screen.findByText("First audio");
    await fireEvent.click(nextButton());
    await screen.findByText("Audio input");
    vi.useFakeTimers({ toFake: [...FAKED_CLOCK] });
    await fireEvent.click(screen.getByLabelText(m.start_recording()));
    await flush();

    const back = screen.getByRole("button", { name: "Tillbaka" }) as HTMLButtonElement;
    const firstPageDot = screen.getByRole("button", {
      name: "Steg 1 i flödet"
    }) as HTMLButtonElement;
    expect(back.disabled).toBe(true);
    expect(firstPageDot.disabled).toBe(true);
    const reasonId = back.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(reasonId)?.textContent?.trim()).toBe(
      "Stoppa inspelningen för steg 2: Audio input."
    );
    expect(firstPageDot.getAttribute("aria-describedby")).toBe(reasonId);
    await fireEvent.click(back);
    await fireEvent.click(firstPageDot);
    await flush();
    expect(screen.getByText("Audio input")).toBeTruthy();
    expect(media.recorders[0]?.state).toBe("recording");

    let finishPersisting = () => {};
    vi.mocked(persistRecordingSegment).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishPersisting = () => resolve({ degraded: false });
        })
    );
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[0]?.finish();
    await flush();
    expect(back.disabled).toBe(true);

    finishPersisting();
    await flush();
    expect(back.disabled).toBe(false);
    await fireEvent.click(back);
    expect(await screen.findByText("First audio")).toBeTruthy();
  });

  it("holds a stopped step until its last segment is handed over, and a close waits for it", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(({ file }: { file: File }) => pendingUpload(pendingUploads, file));
    renderDialog(upload, { steps: [firstAudioStep, { ...audioStep, step_order: 2 }] });
    await screen.findByText("First audio");
    await fireEvent.click(nextButton());
    await screen.findByText("Audio input");
    vi.useFakeTimers({ toFake: [...FAKED_CLOCK] });
    await fireEvent.click(screen.getByLabelText(m.start_recording()));
    await flush();
    // The first segment is uploaded, so nothing but the recording holds the step.
    await rotate();
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    pendingUploads[0]?.resolve(uploadedFile("segment-0", pendingUploads[0].file.name));
    await flush();

    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    await flush();
    // Stopped, but the browser has not handed over the last segment yet.
    const back = screen.getByRole("button", { name: "Tillbaka" }) as HTMLButtonElement;
    const firstPageDot = screen.getByRole("button", {
      name: "Steg 1 i flödet"
    }) as HTMLButtonElement;
    expect(back.disabled).toBe(true);
    expect(firstPageDot.disabled).toBe(true);
    expect(nextButton().disabled).toBe(true);
    await fireEvent.click(back);
    await fireEvent.click(firstPageDot);
    await fireEvent.click(nextButton());
    await flush();
    expect(screen.getByText("Audio input")).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await fireEvent.click(screen.getByRole("button", { name: "Stäng ändå" }));
    await flush();
    media.recorders[1]?.finish();
    await flush();

    // The last segment reached the local store, under the step that recorded it.
    expect(
      vi
        .mocked(persistRecordingSegment)
        .mock.calls.map(([args]) => [args.stepId, args.segmentIndex, args.reason])
    ).toEqual([
      ["step-audio", 0, "rotation"],
      ["step-audio", 1, "manual"]
    ]);
  });

  it("counts recovered segments whose upload fails and retries them in segment order", async () => {
    vi.mocked(scanRecoverableSessionsForSteps).mockResolvedValue({
      "step-audio": [recoveryHint()]
    });
    vi.mocked(readSessionRecords).mockResolvedValue([
      segmentRecord(0, "recovered-0"),
      segmentRecord(1),
      segmentRecord(2),
      segmentRecord(3)
    ]);
    let failUploads = true;
    const upload = vi.fn(async ({ file }: { file: File }) => {
      if (failUploads) throw new Error("Network down");
      return uploadedFile(`uploaded-${file.name}`, file.name);
    });
    renderDialog(upload);

    await fireEvent.click(
      await screen.findByRole("button", { name: m.recording_resume_continue_recording() })
    );
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(requireFailedRecordingAlert()).toBeTruthy());

    const start = screen.getByLabelText(m.start_recording()) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    expect(screen.getByText(m.recording_stopped_upload_backlog())).toBeTruthy();

    failUploads = false;
    await fireEvent.click(retryInFailedRecordingAlert());
    await waitFor(() => expect(markSegmentUploaded).toHaveBeenCalledTimes(3));
    expect(markedSegments().map(([segmentIndex]) => segmentIndex)).toEqual([1, 2, 3]);
    await waitFor(() => expect(start.disabled).toBe(false));
    expect(failedRecordingAlert()).toBeNull();
  });

  it("keeps one live text session across a rotation and ends it with the recording", async () => {
    installLiveTranscriptFakes();
    const createSession = vi.fn(async () => liveSession);
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    await openDialogAndStartRecording(upload, {
      createSession,
      transcription: {
        live: { available: true, reason: null },
        speaker_labels: { selectable: true, required: false, default: true }
      }
    });

    const socket = FakeLiveSocket.instances[0];
    expect(socket?.protocols).toEqual(["eneo-live.v1", "ticket.t0k3n"]);
    socket.open();
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    await flush();
    expect(screen.getByText(m.live_transcription_listening())).toBeTruthy();

    await rotate();
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    expect(media.recorders).toHaveLength(2);
    expect(socket.texts).toEqual([]);
    expect(socket.close).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[1]?.finish();
    await flush();
    expect(socket.texts).toEqual([JSON.stringify({ type: "stop" })]);
    expect(createSession).toHaveBeenCalledOnce();
  });

  it("starts the recording once the live text has tapped the audio, so it hears the first word", async () => {
    installLiveTranscriptFakes();
    const loadWorklet = holdWorklet();
    await openDialog(
      vi.fn(() => new Promise<UploadedFile>(() => undefined)),
      liveText
    );

    await fireEvent.click(screen.getByLabelText(m.start_recording()));
    await flush();
    expect(media.addModule).toHaveBeenCalledOnce();
    expect(media.recorders).toHaveLength(0);

    loadWorklet();
    await flush();
    expect(FakeWorkletNode.instances).toHaveLength(1);
    expect(media.recorders).toHaveLength(1);
    expect(media.recorders[0]?.state).toBe("recording");
  });

  it("records on time, and says live text is unavailable, when the tap takes too long", async () => {
    installLiveTranscriptFakes();
    const loadWorklet = holdWorklet();
    await openDialog(
      vi.fn(() => new Promise<UploadedFile>(() => undefined)),
      liveText
    );

    await fireEvent.click(screen.getByLabelText(m.start_recording()));
    await flush();
    vi.advanceTimersByTime(AUDIO_GRAPH_PREPARATION_MS - 1);
    await flush();
    expect(media.recorders).toHaveLength(0);
    vi.advanceTimersByTime(1);
    await flush();
    expect(media.recorders).toHaveLength(1);
    expect(media.recorders[0]?.state).toBe("recording");
    expect(screen.getByText(m.live_transcription_unavailable())).toBeTruthy();

    loadWorklet();
    await flush();
    expect(FakeWorkletNode.instances).toHaveLength(0);
  });
});

describe("FlowRunDialog live text across a rotation", () => {
  it("keeps the tap and the one socket through a rotation, and the text keeps arriving", async () => {
    installLiveTranscriptFakes();
    const createSession = vi.fn(async () => liveSession);
    await openDialogAndStartRecording(
      vi.fn(() => new Promise<UploadedFile>(() => undefined)),
      {
        ...liveText,
        createSession
      }
    );
    const socket = FakeLiveSocket.instances[0];
    const node = FakeWorkletNode.instances[0];
    socket.open();
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    socket.receive({ type: "transcript.delta", text: "Före" });

    await rotate();
    node.frame(1);
    socket.receive({ type: "transcript.delta", text: " under" });
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    node.frame(2);
    socket.receive({ type: "transcript.delta", text: " efter" });
    await flush();

    expect(screen.getByRole("log").textContent).toBe("Före under efter");
    expect(frameTags(socket)).toEqual([1, 2]);
    expect(media.addModule).toHaveBeenCalledOnce();
    expect(FakeWorkletNode.instances).toHaveLength(1);
    expect(node.port.close).not.toHaveBeenCalled();
    expect(createSession).toHaveBeenCalledOnce();
    expect(FakeLiveSocket.instances).toHaveLength(1);
  });

  it("sends the last audio, then asks for the final text once, when stopped during the overlap", async () => {
    installLiveTranscriptFakes();
    await openDialogAndStartRecording(
      vi.fn(() => new Promise<UploadedFile>(() => undefined)),
      liveText
    );
    const socket = FakeLiveSocket.instances[0];
    const node = FakeWorkletNode.instances[0];
    node.answersFlush = false;
    socket.open();
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    const flushRequests = () =>
      node.port.postMessage.mock.calls.filter(([message]) => message === PCM16_FLUSH);

    await rotate();
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    // The live text ends with the recording, before either file is handed over.
    expect(flushRequests()).toHaveLength(1);
    media.recorders[0]?.finish();
    media.recorders[1]?.finish();
    await flush();
    expect(flushRequests()).toHaveLength(1);
    expect(socket.texts).toEqual([]);

    node.frame(9, 1600);
    node.post(PCM16_FLUSHED);
    await flush();
    expect(frameTags(socket)).toEqual([9]);
    expect(socket.texts).toEqual([JSON.stringify({ type: "stop" })]);
    expect(socket.sent.at(-1)).toBe(JSON.stringify({ type: "stop" }));
    expect(flushRequests()).toHaveLength(1);
  });

  it("ends the live text in the task the recorder stops, so it hears only what the file has", async () => {
    installLiveTranscriptFakes();
    await openDialogAndStartRecording(
      vi.fn(() => new Promise<UploadedFile>(() => undefined)),
      liveText
    );
    const socket = FakeLiveSocket.instances[0];
    const node = FakeWorkletNode.instances[0];
    node.answersFlush = false;
    socket.open();
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    node.frame(1);

    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    expect(node.port.postMessage).toHaveBeenCalledWith(PCM16_FLUSH);
    node.frame(2, 1600);
    node.post(PCM16_FLUSHED);
    // Audio the recorder's last chunk may still bring is not live text's.
    node.frame(3);
    media.recorders[0]?.finish();
    await flush();

    expect(frameTags(socket)).toEqual([1, 2]);
    expect(socket.texts).toHaveLength(1);
  });

  it("keeps a rotated recording's draft until Kasta actually runs, then drops it for good", async () => {
    installLiveTranscriptFakes();
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(({ file }: { file: File }) => pendingUpload(pendingUploads, file));
    await openDialogAndStartRecording(upload, liveText);
    const socket = FakeLiveSocket.instances[0];
    socket.open();
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    socket.receive({ type: "transcript.delta", text: "Anna talar" });
    const discard = () => queryInFailedRecordingAlert(m.discard()) as HTMLButtonElement;

    await rotate();
    await endOverlap();
    media.recorders[0]?.finish();
    await flush();
    pendingUploads[0]?.reject(new Error("Network down"));
    await flush();
    // Capture is still in flight, so Kasta is refused and the draft stays.
    expect(discard().disabled).toBe(true);
    await fireEvent.click(discard());
    await flush();
    expect(screen.getByRole("log").textContent).toBe("Anna talar");

    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[1]?.finish();
    await flush();
    // The last segment's upload is in flight: still refused.
    expect(discard().disabled).toBe(true);
    await fireEvent.click(discard());
    await flush();
    expect(screen.getByRole("log").textContent).toBe("Anna talar");

    pendingUploads[1]?.resolve(uploadedFile("segment-1", pendingUploads[1].file.name));
    await flush();
    expect(discard().disabled).toBe(false);
    await fireEvent.click(discard());
    await flush();
    socket.receive({ type: "transcript.delta", text: " vidare" });
    socket.receive({ type: "transcript.done", text: "Anna talar vidare." });
    await flush();

    expect(screen.queryByRole("log")).toBeNull();
    expect(screen.queryByText(/Anna talar/)).toBeNull();
  });
});

describe("FlowRunDialog live transcript in the run", () => {
  const ready = { type: "ready", sample_rate: 16000, max_seconds: 18000 };
  const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile("file-1", file.name));

  // Records one file with live text that heard all of it: the stop is sent,
  // counted, and the file is uploaded; the final text is still to come.
  async function recordHeardWhole(
    options: DialogOptions = {},
    { beforeReview = async () => {} }: { beforeReview?: () => Promise<void> } = {}
  ) {
    installLiveTranscriptFakes();
    let uploads = 0;
    const uploadEach = vi.fn(async ({ file }: { file: File }) =>
      uploadedFile(`file-${(uploads += 1)}`, file.name)
    );
    await openDialogAndStartRecording(uploadEach, { ...liveText, ...options });
    const socket = FakeLiveSocket.instances[0];
    socket.open();
    socket.receive(ready);
    FakeWorkletNode.instances[0].frame(1);
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    await flush();
    media.recorders[0]?.finish();
    await flush();
    expect(socket.texts).toEqual([JSON.stringify({ type: "stop", produced_samples: 1600 })]);
    await beforeReview();
    await fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
    await flush();
    return socket;
  }

  const removeRecordedFile = async () => {
    await fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`^${m.delete()} recording-`) })
    );
    await flush();
  };

  const startButton = () =>
    screen.getByRole("button", {
      name: new RegExp(`${m.flow_run_trigger_confirm()}|${m.flow_run_finishing_live_text()}`)
    });
  const stepInputs = (create: ReturnType<typeof vi.fn>) =>
    create.mock.calls.map((call) => (call as unknown as [{ step_inputs: unknown }])[0].step_inputs);

  it("starts the run with the transcript of a recording heard whole, beside its one file", async () => {
    const create = vi.fn(async () => ({ id: "run-1" }));
    const socket = await recordHeardWhole({ create });
    socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "transcript-1" });
    await flush();

    await fireEvent.click(startButton());
    await flush();

    expect(stepInputs(create)).toEqual([
      { "step-audio": { file_ids: ["file-1"], live_transcript_id: "transcript-1" } }
    ]);
  });

  it("keeps the count when the recorder's release closes its context before the last audio", async () => {
    installLiveTranscriptFakes();
    await openDialogAndStartRecording(upload, liveText);
    const socket = FakeLiveSocket.instances[0];
    const node = FakeWorkletNode.instances[0];
    node.answersFlush = false;
    socket.open();
    socket.receive(ready);
    node.frame(1);

    // A browser's order: the recorder hands over its file and closes its
    // context, and only then does the worklet answer the stop.
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[0]?.finish();
    await flush();
    expect(media.contexts[0]?.close).toHaveBeenCalledOnce();
    node.post(PCM16_FLUSHED);

    expect(socket.texts).toEqual([JSON.stringify({ type: "stop", produced_samples: 1600 })]);
  });

  it("leaves the text a preview when the recorder pauses on its own", async () => {
    installLiveTranscriptFakes();
    await openDialogAndStartRecording(upload, liveText);
    const socket = FakeLiveSocket.instances[0];
    socket.open();
    socket.receive(ready);

    media.recorders[0]?.dispatchEvent(new Event("pause"));
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    await flush();

    expect(socket.texts).toEqual([JSON.stringify({ type: "stop" })]);
  });

  it("waits for the final text: the button says so, and a press sends nothing, now or later", async () => {
    const create = vi.fn(async () => ({ id: "run-1" }));
    const socket = await recordHeardWhole({ create });

    expect(startButton().textContent).toContain(m.flow_run_finishing_live_text());
    expect(startButton().getAttribute("aria-disabled")).toBe("true");
    expect((startButton() as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(startButton());
    socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "transcript-1" });
    await flush();

    expect(create).not.toHaveBeenCalled();
    expect(startButton().textContent).toContain(m.flow_run_trigger_confirm());
    expect(startButton().getAttribute("aria-disabled")).toBeNull();
    await fireEvent.click(startButton());
    await flush();
    expect(stepInputs(create)).toEqual([
      { "step-audio": { file_ids: ["file-1"], live_transcript_id: "transcript-1" } }
    ]);
  });

  it("does not wait for text that can no longer go with the run's file", async () => {
    const create = vi.fn(async () => ({ id: "run-1" }));
    await recordHeardWhole(
      { create },
      {
        beforeReview: async () => {
          await removeRecordedFile();
          await fireEvent.drop(screen.getByRole("button", { name: /Audio input/ }), {
            dataTransfer: { files: [new File(["audio"], "other.webm", { type: "audio/webm" })] }
          });
          await flush();
        }
      }
    );

    expect(startButton().textContent).toContain(m.flow_run_trigger_confirm());
    expect(startButton().getAttribute("aria-disabled")).toBeNull();
    await fireEvent.click(startButton());
    await flush();
    expect(stepInputs(create)).toEqual([{ "step-audio": { file_ids: ["file-2"] } }]);
  });

  it("does not wait for text once its file is removed from an optional step", async () => {
    const create = vi.fn(async () => ({ id: "run-1" }));
    await recordHeardWhole(
      { create, steps: [{ ...audioStep, required: false }] },
      { beforeReview: removeRecordedFile }
    );

    expect(startButton().textContent).toContain(m.flow_run_trigger_confirm());
    expect(startButton().getAttribute("aria-disabled")).toBeNull();
    await fireEvent.click(startButton());
    await flush();
    expect(create).toHaveBeenCalledOnce();
  });

  it("waits FINAL_TEXT_WAIT_MS at most; a later final text never changes a repeated request", async () => {
    const create = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ id: "run-1" });
    const socket = await recordHeardWhole({ create });

    vi.advanceTimersByTime(FINAL_TEXT_WAIT_MS);
    await flush();
    expect(startButton().getAttribute("aria-disabled")).toBeNull();
    await fireEvent.click(startButton());
    await flush();
    socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "transcript-1" });
    await fireEvent.click(startButton());
    await flush();

    expect(stepInputs(create)).toEqual([
      { "step-audio": { file_ids: ["file-1"] } },
      { "step-audio": { file_ids: ["file-1"] } }
    ]);
  });

  it("asks once more without a transcript Eneo will not use, and says nothing about it", async () => {
    const refusal = new EneoError("Unavailable", "RESPONSE", 404, 0, {
      code: "flow_run_live_transcript_not_found",
      message: "The live transcript is unavailable."
    });
    const create = vi.fn().mockRejectedValueOnce(refusal).mockResolvedValueOnce({ id: "run-1" });
    const socket = await recordHeardWhole({ create });
    socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "transcript-1" });
    await flush();

    await fireEvent.click(startButton());
    await flush();

    expect(stepInputs(create)).toEqual([
      { "step-audio": { file_ids: ["file-1"], live_transcript_id: "transcript-1" } },
      { "step-audio": { file_ids: ["file-1"] } }
    ]);
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith(m.flow_run_started_toast());
  });
});

const liveText: DialogOptions = {
  createSession: vi.fn(async () => liveSession),
  transcription: {
    live: { available: true, reason: null },
    speaker_labels: { selectable: true, required: false, default: true }
  }
};

// Holds the worklet module's load until the test lets it finish.
function holdWorklet(): () => void {
  let finish: () => void = () => {};
  media.addModule.mockImplementation(
    () => new Promise<undefined>((resolve) => (finish = () => resolve(undefined)))
  );
  return () => finish();
}

type PendingUpload = {
  file: File;
  resolve: (file: UploadedFile) => void;
  reject: (error: Error) => void;
};

function pendingUpload(pendingUploads: PendingUpload[], file: File) {
  return new Promise<UploadedFile>((resolve, reject) => {
    pendingUploads.push({ file, resolve, reject });
  });
}

// Lets awaited work (getUserMedia, persistence, the upload queue) settle under
// the fake clock.
const flush = () => vi.advanceTimersByTimeAsync(0);

// The session's rotation: the next recorder starts, the replaced one keeps
// running until the overlap ends.
async function rotate() {
  vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
  await flush();
}

async function endOverlap() {
  vi.advanceTimersByTime(ROTATION_OVERLAP_MS);
  await flush();
}

type Upload = (args: { file: File; stepId: string }) => Promise<UploadedFile>;
type DialogOptions = {
  create?: () => Promise<unknown>;
  steps?: FlowRunContractStepInput[];
  transcription?: FlowRunContractTranscription | null;
  createSession?: () => Promise<FlowLiveTranscriptionSession>;
};

function renderDialog(upload: Upload, options: DialogOptions = {}) {
  return render(FlowRunDialog, {
    open: true,
    flow: {
      id: "flow-1",
      name: "Recording flow",
      steps: [{ id: "step-audio" }]
    } as unknown as Flow,
    eneo: buildEneo(upload, options),
    lastInputPayload: null
  });
}

async function openDialog(upload: Upload, options: DialogOptions = {}) {
  const rendered = renderDialog(upload, options);
  await screen.findByText("Audio input");
  vi.useFakeTimers({ toFake: [...FAKED_CLOCK] });
  return rendered;
}

async function openDialogAndStartRecording(upload: Upload, options: DialogOptions = {}) {
  const rendered = await openDialog(upload, options);
  await fireEvent.click(screen.getByLabelText(m.start_recording()));
  await flush();
  expect(media.recorders).toHaveLength(1);
  return rendered;
}

// The recorders' states each time the microphone is released: it must not be
// released while any of them still records.
function recorderStatesAtRelease() {
  const states: RecordingState[][] = [];
  media.track.stop.mockImplementation(() => {
    states.push(media.recorders.map(({ state }) => state));
  });
  return states;
}

function persistedSegments() {
  return vi
    .mocked(persistRecordingSegment)
    .mock.calls.map(([args]) => ({ segmentIndex: args.segmentIndex, reason: args.reason }));
}

function markedSegments() {
  return vi
    .mocked(markSegmentUploaded)
    .mock.calls.map(([args]) => [args.segmentIndex, args.uploadedFileId]);
}

function nextButton() {
  return screen.getByRole("button", { name: "Nästa" }) as HTMLButtonElement;
}

// The step's alert for recorded audio whose upload failed.
function failedRecordingAlert(): HTMLElement | null {
  return (
    screen
      .queryAllByRole("alert")
      .find((alert) => within(alert).queryByText(m.recording_last_clip_ready())) ?? null
  );
}

function requireFailedRecordingAlert(): HTMLElement {
  const alert = failedRecordingAlert();
  if (!alert) throw new Error("The failed recording alert is not shown");
  return alert;
}

function retryInFailedRecordingAlert() {
  return within(requireFailedRecordingAlert()).getByRole("button", { name: "Försök igen" });
}

function queryInFailedRecordingAlert(name: string) {
  return within(requireFailedRecordingAlert()).queryByRole("button", { name });
}

function discardButton() {
  return within(requireFailedRecordingAlert()).getByRole("button", {
    name: m.discard()
  }) as HTMLButtonElement;
}

// Discard shows why it is disabled, and a click on it changes nothing.
async function expectDiscardRefused() {
  const discard = discardButton();
  expect(discard.disabled).toBe(true);
  const reasonId = discard.getAttribute("aria-describedby") ?? "";
  expect(document.getElementById(reasonId)?.textContent?.trim()).toBe(DISCARD_BUSY_REASON);
  await fireEvent.click(discard);
  await flush();
  expect(purgeSession).not.toHaveBeenCalled();
  expect(failedRecordingAlert()).toBeTruthy();
}

function installFakeMedia() {
  const track = Object.assign(new EventTarget(), {
    kind: "audio",
    readyState: "live",
    stop: vi.fn()
  });
  const stream = Object.assign(new EventTarget(), {
    active: true,
    getAudioTracks: () => [track]
  });
  const recorders: FakeMediaRecorder[] = [];
  const contexts: FakeAudioContext[] = [];
  const getUserMedia = vi.fn(async (): Promise<unknown> => stream);
  const addModule = vi.fn(async (_url: string): Promise<undefined> => undefined);

  class FakeMediaRecorder extends EventTarget {
    static isTypeSupported = () => true;
    state: RecordingState = "inactive";
    readonly mimeType = "audio/webm;codecs=opus";

    constructor(readonly stream: unknown) {
      super();
      recorders.push(this);
    }

    start() {
      this.state = "recording";
    }

    stop() {
      this.state = "inactive";
    }

    requestData() {}

    // What a browser does shortly after stop(): hand over the last chunk (none
    // when nothing was captured), then report that the recorder stopped.
    finish({ withAudio = true }: { withAudio?: boolean } = {}) {
      if (this.state !== "inactive") throw new Error("A recorder finishes only after stop()");
      if (withAudio) {
        const chunk = Object.assign(new Event("dataavailable"), {
          data: new Blob(["audio"], { type: this.mimeType })
        });
        this.dispatchEvent(chunk);
      }
      this.dispatchEvent(new Event("stop"));
    }
  }

  class FakeAudioContext extends EventTarget {
    state = "running";
    audioWorklet = { addModule };
    close = vi.fn(async () => {
      this.state = "closed";
      this.dispatchEvent(new Event("statechange"));
    });

    constructor() {
      super();
      contexts.push(this);
    }

    createAnalyser() {
      return { fftSize: 32, getFloatTimeDomainData: () => undefined };
    }

    createMediaStreamSource() {
      return { connect: () => undefined, disconnect: () => undefined };
    }
  }

  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  // The finished clip's preview player; jsdom has no media playback.
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia }
  });
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: () => "blob:recording"
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: () => undefined
  });

  return {
    track,
    stream,
    recorders,
    contexts,
    getUserMedia,
    addModule,
    uninstall() {
      vi.unstubAllGlobals();
      Reflect.deleteProperty(navigator, "mediaDevices");
      Reflect.deleteProperty(URL, "createObjectURL");
      Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  };
}

const audioStep: FlowRunContractStepInput = {
  step_id: "step-audio",
  step_order: 1,
  label: "Audio input",
  required: true,
  input_format: "audio",
  accepted_mimetypes: ["audio/webm"],
  max_files: 10,
  max_file_size_bytes: 1_000_000
};

const firstAudioStep: FlowRunContractStepInput = {
  ...audioStep,
  step_id: "step-first",
  label: "First audio",
  required: false
};

const audioStepSnapshot = {
  publishedFlowVersion: 7,
  maxFiles: 10,
  maxFileSizeBytes: 1_000_000,
  acceptedMimetypes: ["audio/webm"],
  inputFormat: "audio"
};

function buildEneo(
  upload: Upload,
  {
    create = vi.fn(async () => ({ id: "run-1" })),
    steps = [audioStep],
    transcription = null,
    createSession = vi.fn()
  }: DialogOptions = {}
): Eneo {
  const contract: FlowRunContract = {
    flow_id: "flow-1",
    published_flow_version: 7,
    form_fields: [],
    steps_requiring_input: steps,
    template_readiness: [],
    transcription
  };
  return {
    flows: {
      runContract: { get: vi.fn(async () => contract) },
      liveTranscription: { createSession },
      steps: { runtimeFiles: { upload } },
      runs: {
        deriveUploadIntentIdempotencyKey: vi.fn(async () => "derived-key"),
        create
      }
    },
    files: { delete: vi.fn(async () => undefined) },
    client: { baseUrl: new URL("https://eneo.example.test") }
  } as unknown as Eneo;
}

function uploadedFile(id: string, name: string): UploadedFile {
  return {
    id,
    name,
    mimetype: "audio/webm",
    size: 5,
    created_at: "2026-09-23T00:00:00Z"
  } as UploadedFile;
}

function recoveryHint(): SessionRecoveryHint {
  return {
    flowId: "flow-1",
    stepId: "step-audio",
    sessionId: "session-1",
    segmentCount: 4,
    totalDurationMs: 4_000,
    earliestCapturedAt: Date.UTC(2026, 8, 23),
    uploadedCount: 1,
    contractSnapshot: audioStepSnapshot
  };
}

function segmentRecord(segmentIndex: number, uploadedFileId: string | null = null): SegmentRecord {
  return {
    flowId: "flow-1",
    stepId: "step-audio",
    sessionId: "session-1",
    segmentIndex,
    blob: new Blob(["recording"], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 1_000,
    capturedAt: Date.UTC(2026, 8, 23, 9, segmentIndex),
    uploadedFileId,
    reason: "rotation",
    contractSnapshot: audioStepSnapshot
  };
}
