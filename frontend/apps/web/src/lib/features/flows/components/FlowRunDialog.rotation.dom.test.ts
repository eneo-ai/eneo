import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type {
  Eneo,
  Flow,
  FlowRunContract,
  FlowRunContractStepInput,
  UploadedFile
} from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  markSegmentUploaded,
  persistRecordingSegment
} from "$lib/features/audio/flowRunRecordingSession";
import { SEGMENT_ROTATION_MS } from "$lib/features/audio/recordingSession";
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

let media: ReturnType<typeof installFakeMedia>;

beforeEach(() => {
  media = installFakeMedia();
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

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    await flush();
    media.recorders[0]?.finish();
    await flush();

    expect(media.recorders).toHaveLength(2);
    expect(media.recorders[1]?.stream).toBe(media.stream);
    expect(media.recorders[1]?.state).toBe("recording");
    expect(media.track.stop).not.toHaveBeenCalled();
    expect(media.contexts).toHaveLength(1);
    expect(media.contexts[0]?.close).not.toHaveBeenCalled();
    expect(persistedSegments()).toEqual([{ segmentIndex: 0, reason: "rotation" }]);
    expect(upload).toHaveBeenCalledOnce();
    expect(screen.getByLabelText(m.stop_recording())).toBeTruthy();
  });

  it("persists and uploads both segments once when the user stops during a rotation", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(
      ({ file }: { file: File }) =>
        new Promise<UploadedFile>((resolve) => {
          pendingUploads.push({ file, resolve });
        })
    );
    await openDialogAndStartRecording(upload);

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    await flush();
    // The replaced recorder has not handed over its file when the user stops.
    await fireEvent.click(screen.getByLabelText(m.stop_recording()));
    media.recorders[0]?.finish();
    media.recorders[1]?.finish();
    await flush();

    expect(persistedSegments()).toEqual([
      { segmentIndex: 0, reason: "rotation" },
      { segmentIndex: 1, reason: "manual" }
    ]);
    pendingUploads[0]?.resolve(uploadedFile("segment-0", pendingUploads[0].file.name));
    await flush();
    pendingUploads[1]?.resolve(uploadedFile("segment-1", pendingUploads[1].file.name));
    await flush();

    expect(upload).toHaveBeenCalledTimes(2);
    expect(
      vi
        .mocked(markSegmentUploaded)
        .mock.calls.map(([args]) => [args.segmentIndex, args.uploadedFileId])
    ).toEqual([
      [0, "segment-0"],
      [1, "segment-1"]
    ]);
    expect(screen.getByText(/-seg00-/)).toBeTruthy();
    expect(screen.getByText(/-seg01-/)).toBeTruthy();
    expect(media.track.stop).toHaveBeenCalledOnce();
    expect(media.contexts[0]?.close).toHaveBeenCalledOnce();

    // The session ended with the recording, so no rotation reaches the idle recorder.
    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    await flush();
    expect(media.recorders).toHaveLength(2);
    expect(screen.getByLabelText(m.start_recording())).toBeTruthy();
  });

  it("stops with a visible message when a rotation would leave three segments waiting for upload", async () => {
    const upload = vi.fn(() => new Promise<UploadedFile>(() => undefined));
    await openDialogAndStartRecording(upload);

    for (const finished of [0, 1]) {
      vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
      await flush();
      expect(media.recorders).toHaveLength(finished + 2);
      media.recorders[finished]?.finish();
      await flush();
    }
    expect(screen.getByLabelText(m.stop_recording())).toBeTruthy();

    vi.advanceTimersByTime(SEGMENT_ROTATION_MS);
    await flush();
    media.recorders[2]?.finish();
    await flush();

    expect(media.recorders).toHaveLength(3);
    expect(persistedSegments().map(({ reason }) => reason)).toEqual([
      "rotation",
      "rotation",
      "backlog"
    ]);
    expect(screen.getByText(m.recording_stopped_upload_backlog())).toBeTruthy();
    expect(screen.getByLabelText(m.start_recording())).toBeTruthy();
    expect(media.track.stop).toHaveBeenCalledOnce();
  });

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
});

type PendingUpload = {
  file: File;
  resolve: (file: UploadedFile) => void;
};

// Lets awaited work (getUserMedia, persistence, the upload queue) settle under
// the fake clock.
const flush = () => vi.advanceTimersByTimeAsync(0);

async function openDialogAndStartRecording(
  upload: (args: { file: File; stepId: string }) => Promise<UploadedFile>
) {
  render(FlowRunDialog, {
    open: true,
    flow: {
      id: "flow-1",
      name: "Recording flow",
      steps: [{ id: "step-audio" }]
    } as unknown as Flow,
    eneo: buildEneo(upload),
    lastInputPayload: null
  });
  await screen.findByText("Audio input");
  vi.useFakeTimers({ toFake: [...FAKED_CLOCK] });
  await fireEvent.click(screen.getByLabelText(m.start_recording()));
  await flush();
  expect(media.recorders).toHaveLength(1);
}

function persistedSegments() {
  return vi
    .mocked(persistRecordingSegment)
    .mock.calls.map(([args]) => ({ segmentIndex: args.segmentIndex, reason: args.reason }));
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

    // What a browser does shortly after stop(): hand over the last chunk,
    // then report that the recorder stopped.
    finish() {
      const chunk = Object.assign(new Event("dataavailable"), {
        data: new Blob(["audio"], { type: this.mimeType })
      });
      this.dispatchEvent(chunk);
      this.dispatchEvent(new Event("stop"));
    }
  }

  class FakeAudioContext {
    state = "running";
    close = vi.fn(async () => {
      this.state = "closed";
    });

    constructor() {
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
    value: { getUserMedia: vi.fn(async () => stream) }
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

function buildEneo(upload: (args: { file: File; stepId: string }) => Promise<UploadedFile>): Eneo {
  const contract: FlowRunContract = {
    flow_id: "flow-1",
    published_flow_version: 7,
    form_fields: [],
    steps_requiring_input: [audioStep],
    template_readiness: []
  };
  return {
    flows: {
      runContract: { get: vi.fn(async () => contract) },
      steps: { runtimeFiles: { upload } },
      runs: {
        deriveUploadIntentIdempotencyKey: vi.fn(async () => "derived-key"),
        create: vi.fn()
      }
    },
    files: { delete: vi.fn(async () => undefined) }
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
