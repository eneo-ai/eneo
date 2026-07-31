import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type {
  Eneo,
  Flow,
  FlowRun,
  FlowRunContract,
  FlowRunContractStepInput,
  UploadedFile
} from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  markSegmentUploaded,
  persistRecordingSegment,
  purgeSession,
  readSessionRecords,
  scanRecoverableSessionsForSteps
} from "$lib/features/audio/flowRunRecordingSession";
import type { SegmentRecord, SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
import { m } from "$lib/paraglide/messages";
import FlowRunDialog from "./FlowRunDialog.svelte";

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

vi.mock("$lib/features/audio/AudioRecorder.svelte", () => ({
  default: (
    anchor: Node,
    props: {
      onRecordingDone: (params: {
        blob: Blob;
        mimeType: string;
        reason: "manual" | "stall";
        durationMs: number;
      }) => void;
      onRecordingStateChange?: (active: boolean, meta: { origin: "user" }) => void;
    }
  ) => {
    const startButton = document.createElement("button");
    startButton.type = "button";
    startButton.textContent = "Start test recording";
    startButton.addEventListener("click", () => {
      props.onRecordingStateChange?.(true, { origin: "user" });
    });
    anchor.parentNode?.insertBefore(startButton, anchor);

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Finish test recording";
    button.addEventListener("click", () => {
      props.onRecordingStateChange?.(false, { origin: "user" });
      props.onRecordingDone({
        blob: new Blob(["recording"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        reason: "manual",
        durationMs: 1_000
      });
    });
    anchor.parentNode?.insertBefore(button, anchor);

    const stalledButton = document.createElement("button");
    stalledButton.type = "button";
    stalledButton.textContent = "Finish stalled test recording";
    stalledButton.addEventListener("click", () => {
      props.onRecordingStateChange?.(false, { origin: "user" });
      props.onRecordingDone({
        blob: new Blob(["recording"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        reason: "stall",
        durationMs: 1_000
      });
    });
    anchor.parentNode?.insertBefore(stalledButton, anchor);
  }
}));

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

afterEach(() => {
  vi.useFakeTimers();
  cleanup();
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.mocked(markSegmentUploaded).mockReset().mockResolvedValue(undefined);
  vi.mocked(persistRecordingSegment).mockReset().mockResolvedValue({ degraded: false });
  vi.mocked(purgeSession).mockReset().mockResolvedValue(undefined);
  vi.mocked(readSessionRecords).mockReset().mockResolvedValue([]);
  vi.mocked(scanRecoverableSessionsForSteps).mockReset().mockResolvedValue({});
});

describe("FlowRunDialog recording upload reconciliation", () => {
  it("persists before upload and records the fresh upload response identity", async () => {
    const events: string[] = [];
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(({ file }: { file: File }) => {
      events.push(`upload:${file.name}`);
      return new Promise<UploadedFile>((resolve) => {
        pendingUploads.push({ file, resolve });
      });
    });
    vi.mocked(persistRecordingSegment).mockImplementation(async () => {
      events.push("persist");
      return { degraded: false };
    });

    renderDialog(buildEneo({ upload }));
    await screen.findByText("Audio input");

    const backgroundFile = new File(["other"], "other.webm", { type: "audio/webm" });
    const dropzone = screen.getByRole("button", { name: /Audio input/ });
    await fireEvent.drop(dropzone, { dataTransfer: { files: [backgroundFile] } });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    await fireEvent.click(screen.getByRole("button", { name: "Finish test recording" }));
    await waitFor(() => expect(persistRecordingSegment).toHaveBeenCalledOnce());
    await Promise.resolve();
    await Promise.resolve();
    expect(upload).toHaveBeenCalledTimes(1);

    pendingUploads[0]?.resolve(uploadedFile("unrelated-file", "other.webm"));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect((screen.getByRole("button", { name: "Nästa" }) as HTMLButtonElement).disabled).toBe(
      true
    );
    pendingUploads[1]?.resolve(uploadedFile("recording-file", pendingUploads[1].file.name));

    await waitFor(() =>
      expect(markSegmentUploaded).toHaveBeenCalledWith(
        expect.objectContaining({ uploadedFileId: "recording-file" })
      )
    );
    expect(events.indexOf("persist")).toBeLessThan(
      events.findIndex((event) => event.startsWith("upload:") && event !== "upload:other.webm")
    );
  });

  it("records the resumed upload response identity when another upload settles first", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(
      ({ file }: { file: File }) =>
        new Promise<UploadedFile>((resolve) => {
          pendingUploads.push({ file, resolve });
        })
    );
    const hint = recoveryHint();
    vi.mocked(scanRecoverableSessionsForSteps).mockResolvedValue({
      "step-audio": [hint]
    });
    vi.mocked(readSessionRecords).mockResolvedValue([segmentRecord()]);

    renderDialog(buildEneo({ upload }));
    await screen.findByRole("button", { name: m.recording_resume_continue_recording() });

    const backgroundFile = new File(["other"], "other.webm", { type: "audio/webm" });
    const dropzone = screen.getByRole("button", { name: /Audio input/ });
    await fireEvent.drop(dropzone, { dataTransfer: { files: [backgroundFile] } });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    await fireEvent.click(
      screen.getByRole("button", { name: m.recording_resume_continue_recording() })
    );
    await waitFor(() => expect(readSessionRecords).toHaveBeenCalledOnce());
    await Promise.resolve();
    await Promise.resolve();
    expect(upload).toHaveBeenCalledTimes(1);

    pendingUploads[0]?.resolve(uploadedFile("unrelated-file", "other.webm"));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    pendingUploads[1]?.resolve(uploadedFile("resumed-file", pendingUploads[1].file.name));

    await waitFor(() =>
      expect(markSegmentUploaded).toHaveBeenCalledWith({
        flowId: "flow-1",
        stepId: "step-audio",
        sessionId: hint.sessionId,
        segmentIndex: 0,
        uploadedFileId: "resumed-file"
      })
    );
  });

  it("rechecks same-step capacity after the queued upload settles", async () => {
    let resolveUpload: ((file: UploadedFile) => void) | undefined;
    const upload = vi.fn(
      () =>
        new Promise<UploadedFile>((resolve) => {
          resolveUpload = resolve;
        })
    );

    renderDialog(buildEneo({ upload, steps: [{ ...runtimeStep, max_files: 1 }] }));
    await screen.findByText("Audio input");

    const dropzone = screen.getByRole("button", { name: /Audio input/ });
    await fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [new File(["first"], "first.webm", { type: "audio/webm" })]
      }
    });
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());

    await fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [new File(["second"], "second.webm", { type: "audio/webm" })]
      }
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(upload).toHaveBeenCalledOnce();

    resolveUpload?.(uploadedFile("first-file", "first.webm"));

    await waitFor(() =>
      expect(
        screen.getByText(
          m.flow_run_max_files_exceeded({ attempted: "1", limit: "1", skipped: "1" })
        )
      ).toBeTruthy()
    );
    expect(upload).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Nästa" }) as HTMLButtonElement).disabled).toBe(
        false
      )
    );
  });

  it("isolates queued and in-flight uploads across dialog resets", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(
      ({ file }: { file: File }) =>
        new Promise<UploadedFile>((resolve) => {
          pendingUploads.push({ file, resolve });
        })
    );
    const eneo = buildEneo({ upload, steps: [{ ...runtimeStep, max_files: 1 }] });
    const { rerender, unmount } = renderDialog(eneo);
    await screen.findByText("Audio input");

    const dropzone = screen.getByRole("button", { name: /Audio input/ });
    await fireEvent.drop(dropzone, {
      dataTransfer: { files: [new File(["a"], "a.webm", { type: "audio/webm" })] }
    });
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    await fireEvent.drop(dropzone, {
      dataTransfer: { files: [new File(["q"], "q.webm", { type: "audio/webm" })] }
    });
    await Promise.resolve();
    expect(upload).toHaveBeenCalledOnce();

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await vi.runAllTimersAsync();
    expect(screen.queryByText("Audio input")).toBeNull();
    vi.useRealTimers();

    await rerender(flowRunDialogProps(eneo, true));
    await screen.findByText("Audio input");
    await fireEvent.drop(screen.getByRole("button", { name: /Audio input/ }), {
      dataTransfer: { files: [new File(["b"], "b.webm", { type: "audio/webm" })] }
    });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(pendingUploads.map(({ file }) => file.name)).toEqual(["a.webm", "b.webm"]);

    pendingUploads[0]?.resolve(uploadedFile("old-file", "a.webm"));
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByText("a.webm")).toBeNull();
    expect(screen.queryByText("q.webm")).toBeNull();
    expect(screen.getByText(m.loading())).toBeTruthy();
    expect(pendingUploads.map(({ file }) => file.name)).toEqual(["a.webm", "b.webm"]);

    pendingUploads[1]?.resolve(uploadedFile("new-file", "b.webm"));

    await waitFor(() => expect(screen.getByText("b.webm")).toBeTruthy());
    expect(screen.queryByText(m.loading())).toBeNull();
    expect(screen.queryByText("a.webm")).toBeNull();
    expect(screen.queryByText("q.webm")).toBeNull();
    expect(screen.getByRole("button", { name: /Audio input/ }).getAttribute("aria-disabled")).toBe(
      "true"
    );

    vi.useFakeTimers();
    unmount();
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it("ignores a file selected by a picker opened before the dialog reset", async () => {
    const openedInputs: HTMLInputElement[] = [];
    vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(function (
      this: HTMLInputElement
    ) {
      openedInputs.push(this);
    });
    const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile("fresh-file", file.name));
    const eneo = buildEneo({ upload });
    const { rerender, unmount } = renderDialog(eneo);
    await screen.findByText("Audio input");

    await fireEvent.click(screen.getByRole("button", { name: /Audio input/ }));
    expect(openedInputs).toHaveLength(1);
    const staleInput = openedInputs[0];
    expect(staleInput).toBeDefined();

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await vi.runAllTimersAsync();
    expect(screen.queryByText("Audio input")).toBeNull();
    vi.useRealTimers();

    await rerender(flowRunDialogProps(eneo, true));
    await screen.findByText("Audio input");
    const staleFile = new File(["old"], "old.webm", { type: "audio/webm" });
    Object.defineProperty(staleInput, "files", {
      configurable: true,
      value: [staleFile]
    });
    await fireEvent.change(staleInput);
    await Promise.resolve();
    await Promise.resolve();

    expect(upload).not.toHaveBeenCalled();
    expect(screen.queryByText("old.webm")).toBeNull();
    expect(screen.queryByText(m.loading())).toBeNull();

    const freshFile = new File(["new"], "new.webm", { type: "audio/webm" });
    await fireEvent.drop(screen.getByRole("button", { name: /Audio input/ }), {
      dataTransfer: { files: [freshFile] }
    });

    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByText("new.webm")).toBeTruthy());
    expect(screen.queryByText(m.loading())).toBeNull();

    vi.useFakeTimers();
    unmount();
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it("keeps stale recorded persistence recoverable without mirroring it after reset", async () => {
    let resolvePersistence: ((result: { degraded: boolean }) => void) | undefined;
    vi.mocked(persistRecordingSegment).mockReturnValue(
      new Promise((resolve) => {
        resolvePersistence = resolve;
      })
    );
    const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile("stale-file", file.name));
    const eneo = buildEneo({ upload });
    const { rerender, unmount } = renderDialog(eneo);
    await screen.findByText("Audio input");

    await fireEvent.click(screen.getByRole("button", { name: "Finish test recording" }));
    await waitFor(() => expect(persistRecordingSegment).toHaveBeenCalledOnce());

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await vi.runAllTimersAsync();
    expect(screen.queryByText("Audio input")).toBeNull();
    vi.useRealTimers();

    await rerender(flowRunDialogProps(eneo, true));
    await screen.findByText("Audio input");
    resolvePersistence?.({ degraded: false });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(upload).not.toHaveBeenCalled();
    expect(markSegmentUploaded).not.toHaveBeenCalled();
    expect(purgeSession).not.toHaveBeenCalled();
    expect(screen.queryByText(m.loading())).toBeNull();

    vi.useFakeTimers();
    unmount();
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it("keeps a new recording session active when an old upload settles", async () => {
    const pendingUploads: PendingUpload[] = [];
    const upload = vi.fn(
      ({ file }: { file: File }) =>
        new Promise<UploadedFile>((resolve) => {
          pendingUploads.push({ file, resolve });
        })
    );
    const eneo = buildEneo({ upload });
    const { rerender, unmount } = renderDialog(eneo);
    await screen.findByText("Audio input");

    await fireEvent.click(screen.getByRole("button", { name: "Start test recording" }));
    await fireEvent.click(screen.getByRole("button", { name: "Finish test recording" }));
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await fireEvent.click(screen.getByRole("button", { name: "Stäng ändå" }));
    await vi.runAllTimersAsync();
    expect(screen.queryByText("Audio input")).toBeNull();
    vi.useRealTimers();

    await rerender(flowRunDialogProps(eneo, true));
    await screen.findByText("Audio input");
    await fireEvent.click(screen.getByRole("button", { name: "Start test recording" }));
    await fireEvent.click(screen.getByRole("button", { name: "Finish stalled test recording" }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));

    pendingUploads[0]?.resolve(uploadedFile("old-file", "a.webm"));
    await Promise.resolve();
    await Promise.resolve();

    expect(markSegmentUploaded).not.toHaveBeenCalled();
    expect(screen.getByText(m.loading())).toBeTruthy();
    expect(screen.queryByText("a.webm")).toBeNull();

    pendingUploads[1]?.resolve(uploadedFile("new-file", "b.webm"));

    await waitFor(() =>
      expect(markSegmentUploaded).toHaveBeenCalledWith(
        expect.objectContaining({ uploadedFileId: "new-file" })
      )
    );
    expect(markSegmentUploaded).toHaveBeenCalledOnce();
    expect(screen.getByText("b.webm")).toBeTruthy();
    expect(screen.queryByText("a.webm")).toBeNull();
    await waitFor(() => expect(screen.getByText(m.recording_session_reconnecting())).toBeTruthy());

    vi.useFakeTimers();
    unmount();
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it("does not let a stale resume read attach or finish a new resume action", async () => {
    const hint = recoveryHint();
    const readResolvers: Array<(records: SegmentRecord[]) => void> = [];
    vi.mocked(scanRecoverableSessionsForSteps).mockResolvedValue({
      "step-audio": [hint]
    });
    vi.mocked(readSessionRecords).mockImplementation(
      () =>
        new Promise((resolve) => {
          readResolvers.push(resolve);
        })
    );
    const upload = vi.fn(async ({ file }: { file: File }) =>
      uploadedFile("stale-resume-file", file.name)
    );
    const eneo = buildEneo({ upload });
    const { rerender, unmount } = renderDialog(eneo);

    await fireEvent.click(
      await screen.findByRole("button", { name: m.recording_resume_continue_recording() })
    );
    await waitFor(() => expect(readSessionRecords).toHaveBeenCalledOnce());

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await vi.runAllTimersAsync();
    vi.useRealTimers();

    await rerender(flowRunDialogProps(eneo, true));
    const newResumeButton = await screen.findByRole("button", {
      name: m.recording_resume_continue_recording()
    });
    await fireEvent.click(newResumeButton);
    await waitFor(() => expect(readSessionRecords).toHaveBeenCalledTimes(2));

    const synthesized = segmentRecord();
    synthesized.uploadedFileId = "old-synthesized-file";
    const pending = segmentRecord();
    pending.segmentIndex = 1;
    readResolvers[0]?.([synthesized, pending]);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(upload).not.toHaveBeenCalled();
    expect(screen.queryByText(/session-1/)).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: m.recording_resume_continue_recording()
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);

    readResolvers[1]?.([]);
    await Promise.resolve();
    await Promise.resolve();

    vi.useFakeTimers();
    unmount();
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it("isolates resumed reuploads and ledger marks across resets", async () => {
    const hint = recoveryHint();
    const readResolvers: Array<(records: SegmentRecord[]) => void> = [];
    const pendingUploads: PendingUpload[] = [];
    vi.mocked(scanRecoverableSessionsForSteps).mockResolvedValue({
      "step-audio": [hint]
    });
    vi.mocked(readSessionRecords).mockImplementation(
      () =>
        new Promise((resolve) => {
          readResolvers.push(resolve);
        })
    );
    const upload = vi.fn(
      ({ file }: { file: File }) =>
        new Promise<UploadedFile>((resolve) => {
          pendingUploads.push({ file, resolve });
        })
    );
    const eneo = buildEneo({ upload });
    const { rerender, unmount } = renderDialog(eneo);

    await fireEvent.click(
      await screen.findByRole("button", { name: m.recording_resume_continue_recording() })
    );
    readResolvers[0]?.([segmentRecord()]);
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_trigger_close() }));
    await vi.runAllTimersAsync();
    vi.useRealTimers();

    await rerender(flowRunDialogProps(eneo, true));
    await fireEvent.click(
      await screen.findByRole("button", { name: m.recording_resume_continue_recording() })
    );
    readResolvers[1]?.([segmentRecord()]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));

    pendingUploads[0]?.resolve(uploadedFile("old-resume-file", "old.webm"));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(markSegmentUploaded).not.toHaveBeenCalled();
    expect(screen.getByText(m.loading())).toBeTruthy();

    pendingUploads[1]?.resolve(uploadedFile("new-resume-file", "new.webm"));

    await waitFor(() =>
      expect(markSegmentUploaded).toHaveBeenCalledWith({
        flowId: "flow-1",
        stepId: "step-audio",
        sessionId: hint.sessionId,
        segmentIndex: 0,
        uploadedFileId: "new-resume-file"
      })
    );
    expect(markSegmentUploaded).toHaveBeenCalledOnce();
    expect(screen.getByText("new.webm")).toBeTruthy();
    expect(screen.queryByText("old.webm")).toBeNull();

    vi.useFakeTimers();
    unmount();
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it("keeps different-step uploads independent", async () => {
    const pendingUploads: Array<PendingUpload & { stepId: string }> = [];
    const upload = vi.fn(
      ({ file, stepId }: { file: File; stepId: string }) =>
        new Promise<UploadedFile>((resolve) => {
          pendingUploads.push({ file, stepId, resolve });
        })
    );

    renderDialog(buildEneo({ upload, steps: [runtimeStep, documentRuntimeStep] }));
    await screen.findByText("Audio input");

    await fireEvent.drop(screen.getByRole("button", { name: /Audio input/ }), {
      dataTransfer: {
        files: [new File(["first"], "first.webm", { type: "audio/webm" })]
      }
    });
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    pendingUploads[0]?.resolve(uploadedFile("first-file", "first.webm"));
    await waitFor(() => expect(screen.getByText("first.webm")).toBeTruthy());

    await fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
    await screen.findByText("Document input");
    await fireEvent.drop(screen.getByRole("button", { name: /Document input/ }), {
      dataTransfer: {
        files: [new File(["document"], "document.pdf", { type: "application/pdf" })]
      }
    });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));

    await fireEvent.click(screen.getByRole("button", { name: "Steg 1 i flödet" }));
    await screen.findByText("Audio input");
    await fireEvent.drop(screen.getByRole("button", { name: /Audio input/ }), {
      dataTransfer: {
        files: [new File(["second"], "second.webm", { type: "audio/webm" })]
      }
    });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3));
    expect(pendingUploads.map(({ stepId }) => stepId)).toEqual([
      "step-audio",
      "step-document",
      "step-audio"
    ]);

    pendingUploads[1]?.resolve(uploadedFile("document-file", "document.pdf"));
    pendingUploads[2]?.resolve(uploadedFile("second-file", "second.webm"));
  });

  it("blocks resumed uploads when the persisted recording contract changed", async () => {
    const upload = vi.fn(async () => uploadedFile("should-not-upload", "recording.webm"));
    const hint = recoveryHint();
    hint.contractSnapshot.acceptedMimetypes = ["audio/webm", "audio/ogg"];
    vi.mocked(scanRecoverableSessionsForSteps).mockResolvedValue({
      "step-audio": [hint]
    });
    vi.mocked(readSessionRecords).mockResolvedValue([segmentRecord("audio/ogg")]);

    renderDialog(buildEneo({ upload }));
    await fireEvent.click(
      await screen.findByRole("button", { name: m.recording_resume_continue_recording() })
    );

    await waitFor(() => expect(readSessionRecords).toHaveBeenCalledOnce());
    expect(upload).not.toHaveBeenCalled();
    expect(markSegmentUploaded).not.toHaveBeenCalled();
  });

  it("submits with the idempotency key derived from the uploaded-file intent", async () => {
    const upload = vi.fn(async ({ file }: { file: File }) => uploadedFile("file-1", file.name));
    const deriveUploadIntentIdempotencyKey = vi.fn(async () => "derived-key");
    const create = vi.fn(async () => ({ id: "run-1" }) as FlowRun);

    renderDialog(buildEneo({ upload, deriveUploadIntentIdempotencyKey, create }));
    await screen.findByText("Audio input");

    const dropzone = screen.getByRole("button", { name: /Audio input/ });
    await fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [new File(["audio"], "audio.webm", { type: "audio/webm" })]
      }
    });
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByText("audio.webm")).toBeTruthy());

    await fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
    await fireEvent.click(
      await screen.findByRole("button", { name: m.flow_run_trigger_confirm() })
    );

    await waitFor(() =>
      expect(deriveUploadIntentIdempotencyKey).toHaveBeenCalledWith({
        flowId: "flow-1",
        expectedFlowVersion: 7,
        input_payload_json: {},
        step_inputs: {
          "step-audio": { file_ids: ["file-1"] }
        }
      })
    );
    expect(create).toHaveBeenCalledWith({
      flow: { id: "flow-1" },
      expected_flow_version: 7,
      input_payload_json: {},
      step_inputs: {
        "step-audio": { file_ids: ["file-1"] }
      },
      idempotencyKey: "derived-key"
    });
  });
});

type PendingUpload = {
  file: File;
  resolve: (file: UploadedFile) => void;
};

const runtimeStep: FlowRunContractStepInput = {
  step_id: "step-audio",
  step_order: 1,
  label: "Audio input",
  required: true,
  input_format: "audio",
  accepted_mimetypes: ["audio/webm"],
  max_files: 3,
  max_file_size_bytes: 1_000_000
};

const documentRuntimeStep: FlowRunContractStepInput = {
  ...runtimeStep,
  step_id: "step-document",
  step_order: 2,
  label: "Document input",
  input_format: "file",
  accepted_mimetypes: ["application/pdf"]
};

const matchingContractSnapshot = {
  publishedFlowVersion: 7,
  maxFiles: 3,
  maxFileSizeBytes: 1_000_000,
  acceptedMimetypes: ["audio/webm"],
  inputFormat: "audio"
};

function flowRunDialogProps(eneo: Eneo, open: boolean) {
  return {
    open,
    flow: {
      id: "flow-1",
      name: "Recording flow",
      steps: [{ id: "step-audio" }]
    } as unknown as Flow,
    eneo,
    lastInputPayload: null
  };
}

function renderDialog(eneo: Eneo) {
  return render(FlowRunDialog, flowRunDialogProps(eneo, true));
}

function buildEneo({
  upload,
  deriveUploadIntentIdempotencyKey = vi.fn(async () => "derived-key"),
  create = vi.fn(async () => ({ id: "run-1" }) as FlowRun),
  steps = [runtimeStep]
}: {
  upload: (args: { file: File; stepId: string }) => Promise<UploadedFile>;
  deriveUploadIntentIdempotencyKey?: ReturnType<typeof vi.fn>;
  create?: ReturnType<typeof vi.fn>;
  steps?: FlowRunContractStepInput[];
}): Eneo {
  const contract: FlowRunContract = {
    flow_id: "flow-1",
    published_flow_version: 7,
    form_fields: [],
    steps_requiring_input: steps,
    template_readiness: []
  };
  return {
    flows: {
      runContract: {
        get: vi.fn(async () => contract)
      },
      steps: {
        runtimeFiles: { upload }
      },
      runs: {
        deriveUploadIntentIdempotencyKey,
        create
      }
    },
    files: {
      delete: vi.fn(async () => undefined)
    }
  } as unknown as Eneo;
}

function uploadedFile(id: string, name: string): UploadedFile {
  return {
    id,
    name,
    mimetype: "audio/webm",
    size: 9,
    created_at: "2026-07-20T00:00:00Z"
  } as UploadedFile;
}

function recoveryHint(publishedFlowVersion = 7): SessionRecoveryHint {
  return {
    flowId: "flow-1",
    stepId: "step-audio",
    sessionId: "session-1",
    segmentCount: 1,
    totalDurationMs: 1_000,
    earliestCapturedAt: Date.UTC(2026, 6, 20),
    uploadedCount: 0,
    contractSnapshot: {
      ...matchingContractSnapshot,
      publishedFlowVersion
    }
  };
}

function segmentRecord(mimeType = "audio/webm"): SegmentRecord {
  return {
    flowId: "flow-1",
    stepId: "step-audio",
    sessionId: "session-1",
    segmentIndex: 0,
    blob: new Blob(["recording"], { type: mimeType }),
    mimeType,
    durationMs: 1_000,
    capturedAt: Date.UTC(2026, 6, 20),
    uploadedFileId: null,
    reason: "manual",
    contractSnapshot: matchingContractSnapshot
  };
}
