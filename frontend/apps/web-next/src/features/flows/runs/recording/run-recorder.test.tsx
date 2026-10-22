// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow } from "../../flow-fixtures";
import { makeContract, makeInput } from "../run-fixtures";
import type { RunContract, RunPublic } from "../runs-api";
import { memoryRecordings, type StoredPart } from "./recording-store";
import { fakeLocks } from "./testing/fake-locks";
import { FakeNode, FakeSocket } from "./testing/live-fakes";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../../editor/testing/fixtures").apiStub>
}));

// The device's store, as the form finds it: the test reads and fills it.
const device = vi.hoisted(() => ({
  db: null as unknown as ReturnType<typeof import("./recording-store").memoryRecordings>
}));
vi.mock("./recording-store", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./recording-store")>()),
  indexedDbRecordings: () => device.db
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("../../editor/testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { StartRunDialog } from "../start-run-dialog";

const CONTRACT = "GET /api/v1/flows/{id}/run-contract/";
const START = "POST /api/v1/flows/{id}/runs/";
const LIVE = "POST /api/v1/flows/{id}/steps/{step_id}/live-transcription-sessions/";

/** Runtime uploads as the core answers them; `failNext` drops the connection once. */
class FakeUpload {
  static sent: File[] = [];
  static failNext = false;
  status = 0;
  responseText = "";
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  getResponseHeader() {
    return null;
  }
  abort() {}
  send(body: FormData) {
    const file = body.get("upload_file") as File;
    queueMicrotask(() => {
      if (FakeUpload.failNext) {
        FakeUpload.failNext = false;
        this.onerror?.();
        return;
      }
      FakeUpload.sent.push(file);
      this.status = 201;
      this.responseText = JSON.stringify({
        id: `file-${FakeUpload.sent.length}`,
        name: file.name,
        mimetype: file.type,
        size: file.size
      });
      this.onload?.();
    });
  }
}

/** The browser's recorder: a chunk of audio on every stop. */
class FakeMediaRecorder {
  static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
  state: RecordingState = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: (() => void) | null = null;
  start() {
    this.state = "recording";
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  stop() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.state = "inactive";
    queueMicrotask(() => this.onstop?.(new Event("stop")));
  }
}

/** An audio graph the live text can tap. */
class FakeAudioContext extends EventTarget {
  state = "running";
  audioWorklet = { addModule: vi.fn(() => Promise.resolve()) };
  createMediaStreamSource() {
    return { connect: vi.fn(), disconnect: vi.fn() };
  }
  close() {
    return Promise.resolve();
  }
}

const microphone = vi.fn<() => Promise<MediaStream>>();

function grantMicrophone() {
  const track = Object.assign(new EventTarget(), { stop: vi.fn() });
  microphone.mockResolvedValue({
    getTracks: () => [track],
    getAudioTracks: () => [track]
  } as unknown as MediaStream);
}

function installBrowser({ recorder = true, live = false } = {}) {
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: recorder ? { getUserMedia: microphone } : undefined
  });
  vi.stubGlobal("MediaRecorder", recorder ? FakeMediaRecorder : undefined);
  vi.stubGlobal("AudioContext", live ? FakeAudioContext : undefined);
  vi.stubGlobal("AudioWorkletNode", FakeNode);
  vi.stubGlobal("WebSocket", FakeSocket);
  Object.defineProperty(navigator, "locks", { configurable: true, value: fakeLocks().locks });
}

/** A part of a recording kept on the device from an earlier visit. */
function keptPart(index: number, overrides: Partial<StoredPart> = {}): StoredPart {
  return {
    flowId: "flow-1",
    stepId: "step-1",
    sessionId: "0a1b2c3d-0000-4000-8000-000000000001",
    index,
    blob: new Blob([`part ${index}`], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 30_000,
    capturedAt: Date.UTC(2026, 9, 22, 8, index, 0),
    interrupted: false,
    contract: {
      publishedFlowVersion: 4,
      inputFormat: "audio",
      maxFiles: 4,
      maxFileSizeBytes: null,
      acceptedMimetypes: ["audio/webm", "audio/mp4"]
    },
    ...overrides
  };
}

const audioContract = (live = false): RunContract =>
  makeContract({
    published_flow_version: 4,
    steps_requiring_input: [
      makeInput({
        step_id: "step-1",
        label: "Mötet",
        input_format: "audio",
        accepted_mimetypes: ["audio/webm", "audio/mp4"],
        max_files: 4,
        max_duration_seconds: 7_200,
        max_recording_seconds: 7_200,
        recording_part_seconds: 1_800
      })
    ],
    transcription: {
      live: live ? { available: true } : { available: false, reason: "model_not_realtime" },
      single_recording: true,
      max_speakers: null,
      speaker_labels: {
        default: false,
        required: false,
        selectable: false,
        unavailable_reason: null
      }
    }
  });

function Harness({ onStarted }: { onStarted: (run: RunPublic) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Kör
      </button>
      <StartRunDialog
        flow={makeFlow({ published_version: 4 })}
        open={open}
        onOpenChange={setOpen}
        onStarted={onStarted}
      />
    </>
  );
}

async function openDialog(contract: RunContract) {
  api.routes[CONTRACT] = () => ({ body: contract });
  api.routes[START] = () => ({ status: 201, body: { id: "run-1", status: "queued" } });
  const onStarted = vi.fn();
  renderInApp(<Harness onStarted={onStarted} />);
  fireEvent.click(screen.getByRole("button", { name: "Kör" }));
  const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
  await within(dialog).findByText(/^Mötet/);
  return { dialog, onStarted };
}

const button = (dialog: HTMLElement, name: string) => within(dialog).getByRole("button", { name });

async function recordAndStop(dialog: HTMLElement) {
  fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
  await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
  fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
  return within(dialog).findByText(/^Inspelning, del 1/);
}

function startBody() {
  const call = api.stub.calls.find(
    (item) => item.method === "POST" && item.path.endsWith("/runs/")
  );
  return (call?.init as { body?: unknown } | undefined)?.body as
    Record<string, unknown> | undefined;
}

beforeEach(() => {
  api.routes = {};
  FakeUpload.sent = [];
  FakeUpload.failNext = false;
  FakeSocket.instances = [];
  FakeNode.instances = [];
  microphone.mockReset();
  vi.stubGlobal("XMLHttpRequest", FakeUpload);
  device.db = memoryRecordings();
});

afterEach(() => {
  cleanup();
  api.stub.calls.length = 0;
  vi.unstubAllGlobals();
});

describe("RunRecorder in the start dialog", () => {
  it("explains in plain words a browser that cannot record, with the upload as the way on", async () => {
    installBrowser({ recorder: false });
    const { dialog } = await openDialog(audioContract());
    expect(within(dialog).getByText(messages.flow_transcript_rec_unsupported)).toBeTruthy();
    expect(
      within(dialog).queryByRole("button", { name: messages.flow_transcript_rec_start })
    ).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("explains a refused microphone and how to allow it", async () => {
    installBrowser();
    microphone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    expect(
      await within(dialog).findByText(messages.flow_transcript_rec_permission_denied)
    ).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("records, pauses, stops and starts the run with the recording as the step's audio", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog, onStarted } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_pause });
    expect(within(dialog).getByText(messages.flow_transcript_rec_recording)).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.click(button(dialog, messages.flow_transcript_rec_pause));
    expect(within(dialog).getAllByText(messages.flow_transcript_rec_paused).length).toBeGreaterThan(
      0
    );
    fireEvent.click(button(dialog, messages.flow_transcript_rec_resume));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));

    expect(await within(dialog).findByText(/^Inspelning, del 1/)).toBeTruthy();
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    expect(FakeUpload.sent[0]!.name).toMatch(/^recording-[0-9a-f-]+-seg00-.*Z\.webm$/);
    expect(button(dialog, messages.flow_transcript_rec_continue)).toBeTruthy();

    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({ "step-1": { file_ids: ["file-1"] } });
  });

  it("sends a second recording on the same step as the parts of one recording", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog, onStarted } = await openDialog(audioContract());
    await recordAndStop(dialog);
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_continue })
    );
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 2/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    expect(FakeUpload.sent[1]!.name).toMatch(/-seg01-/);

    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1", "file-2"], single_recording: true }
    });
  });

  it("asks to stop the recording before the run starts", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    expect(await within(dialog).findByText(messages.flow_transcript_rec_stop_first)).toBeTruthy();
    expect(startBody()).toBeUndefined();
  });

  it("asks before closing the dialog throws a recording away", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    fireEvent.click(button(dialog, messages.cancel));
    const confirm = await screen.findByRole("alertdialog", {
      name: messages.flow_transcript_close_title
    });
    await expectNoAxeViolations(document.body);
    fireEvent.click(
      within(confirm).getByRole("button", { name: messages.flow_transcript_close_cancel })
    );
    expect(screen.getByRole("dialog", { name: "Kör Medborgarbrev" })).toBeTruthy();
  });

  it("sends a part whose upload dropped again, by hand or when the browser is back online", async () => {
    installBrowser();
    grantMicrophone();
    FakeUpload.failNext = true;
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    expect(
      await within(dialog).findByText(messages.flow_transcript_upload_offline_hint)
    ).toBeTruthy();
    const retry = within(dialog).getByRole("button", {
      name: /^Försök igen med Inspelning, del 1/
    });
    expect(
      within(dialog).getByRole("button", { name: /^Spara Inspelning, del 1 .* som fil$/ })
    ).toBeTruthy();

    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    await waitFor(() => expect(retry.isConnected).toBe(false));
  });

  it("shows the live text while recording and uses the stored transcript of a recording heard whole", async () => {
    installBrowser({ live: true });
    grantMicrophone();
    api.routes[LIVE] = () => ({
      status: 201,
      body: { ticket: "t0k3n", websocket_path: "/api/v1/live-transcription" }
    });
    const { dialog, onStarted } = await openDialog(audioContract(true));
    expect(within(dialog).getByLabelText(messages.flow_transcript_live_toggle)).toBeTruthy();

    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0]!;
    expect(socket.url).toBe("ws://localhost:3000/api/eneo/api/v1/live-transcription");
    act(() => {
      socket.open();
      socket.receive({ type: "ready" });
      FakeNode.instances[0]!.frame(1);
      socket.receive({ type: "transcript.delta", text: "Välkomna till mötet" });
    });
    const region = await within(dialog).findByRole("region", {
      name: messages.flow_transcript_live_heading
    });
    expect(region.textContent).toBe("Välkomna till mötet");
    expect(region.closest("[aria-live]")).toBeNull();
    await expectNoAxeViolations(document.body);

    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    await waitFor(() => expect(socket.texts).toEqual([{ type: "stop", produced_samples: 1600 }]));

    // The run waits for the final text, which names the stored transcript.
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    act(() => {
      socket.receive({
        type: "transcript.done",
        text: "Välkomna till mötet.",
        transcript_id: "tr-1"
      });
    });
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1"], live_transcript_id: "tr-1" }
    });
  });
});

describe("Keeping a recording on the device", () => {
  it("offers a recording kept from an earlier visit, and goes on with it", async () => {
    installBrowser();
    grantMicrophone();
    await device.db.putPart(keptPart(0));
    await device.db.putPart(keptPart(1, { interrupted: true }));
    const { dialog, onStarted } = await openDialog(audioContract());

    expect(await within(dialog).findByText(messages.flow_transcript_resume_title)).toBeTruthy();
    expect(within(dialog).getByText(/består av 2 delar/)).toBeTruthy();
    expect(within(dialog).getByText(/avbröts när sidan stängdes/)).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.click(button(dialog, messages.flow_transcript_resume_continue));
    expect(await within(dialog).findByText("Inspelning, del 2 (00:30)")).toBeTruthy();
    expect(within(dialog).queryByText(messages.flow_transcript_resume_title)).toBeNull();
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    expect(FakeUpload.sent.map((file) => file.name)).toEqual([
      "recording-0a1b2c3d-0000-4000-8000-000000000001-seg00-2026-10-22T08-00-00-000Z.webm",
      "recording-0a1b2c3d-0000-4000-8000-000000000001-seg01-2026-10-22T08-01-00-000Z.webm"
    ]);

    // Recording again goes on with the kept recording.
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 3/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(3));
    expect(FakeUpload.sent[2]!.name).toMatch(
      /^recording-0a1b2c3d-0000-4000-8000-000000000001-seg02-/
    );
    await waitFor(() => expect(device.db.parts.size).toBe(3));

    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1", "file-2", "file-3"], single_recording: true }
    });
    // The run took the recording: nothing of it stays on the device.
    await waitFor(() => expect(device.db.parts.size).toBe(0));
  });

  it("does not continue a kept recording the step no longer takes", async () => {
    installBrowser();
    await device.db.putPart(keptPart(0, { mimeType: "audio/ogg" }));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(
      await within(dialog).findByText(messages.flow_transcript_resume_type_not_accepted)
    ).toBeTruthy();
    expect(FakeUpload.sent).toHaveLength(0);

    fireEvent.click(button(dialog, messages.flow_transcript_resume_discard));
    await waitFor(() =>
      expect(within(dialog).queryByText(messages.flow_transcript_resume_title)).toBeNull()
    );
    expect(device.db.parts.size).toBe(0);
  });

  it("closes the form and keeps the recording to continue later", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    const later = await within(dialog).findByText(messages.flow_transcript_save_later_hint);
    expect(later).toBeTruthy();

    fireEvent.click(button(dialog, messages.flow_transcript_save_later));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(device.db.parts.size).toBe(1);

    // Opened again, the form offers it.
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const again = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    expect(await within(again).findByText(messages.flow_transcript_resume_title)).toBeTruthy();
  });

  it("throws the recording away from the device when the form closes without it", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    await waitFor(() => expect(device.db.parts.size).toBe(1));
    fireEvent.click(button(dialog, messages.cancel));
    const confirm = await screen.findByRole("alertdialog", {
      name: messages.flow_transcript_close_title
    });
    fireEvent.click(
      within(confirm).getByRole("button", { name: messages.flow_transcript_close_confirm })
    );
    await waitFor(() => expect(device.db.parts.size).toBe(0));
  });
});
