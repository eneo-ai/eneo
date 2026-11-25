// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { initializeBrowserSession, SESSION_GENERATION_HEADER } from "@/lib/api/refusal";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
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
import type { LiveSnapshot } from "./live-transcript";
import { LiveText } from "./run-recorder";

const CONTRACT = "GET /api/v1/flows/{id}/run-contract/";
const START = "POST /api/v1/flows/{id}/runs/";
const LIVE = "POST /api/v1/flows/{id}/steps/{step_id}/live-transcription-sessions/";

/** Runtime uploads as the core answers them; `failNext` drops the connection once. */
class FakeUpload {
  static sent: File[] = [];
  static failNext = false;
  static failAll = false;
  /** The core refuses the next upload for good (a 4xx that sending again does not change). */
  static refuseNext = false;
  /** The core refuses every upload whose file name matches, for good. */
  static refuseNamed: RegExp | null = null;
  status = 0;
  responseText = "";
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  getAllResponseHeaders() {
    return `${SESSION_GENERATION_HEADER}: session-a\r\n`;
  }
  abort() {}
  send(body: FormData) {
    const file = body.get("upload_file") as File;
    queueMicrotask(() => {
      if (FakeUpload.failNext || FakeUpload.failAll) {
        FakeUpload.failNext = false;
        this.onerror?.();
        return;
      }
      if (FakeUpload.refuseNext || FakeUpload.refuseNamed?.test(file.name)) {
        FakeUpload.refuseNext = false;
        this.status = 422;
        this.responseText = JSON.stringify({ message: "Refused" });
        this.onload?.();
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
  requestData() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
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
  createAnalyser() {
    return { fftSize: 4, getFloatTimeDomainData: (buffer: Float32Array) => buffer.fill(0.05) };
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
  return track;
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
  browserLocks = fakeLocks();
  Object.defineProperty(navigator, "locks", { configurable: true, value: browserLocks.locks });
}

/** The browser's Web Locks, shared by every form the test opens, as by the tabs of a browser. */
let browserLocks = fakeLocks();
/** The lock a form holds while it records or has continued the kept recording. */
const HOLD = "eneo-flow-recording-holder:flow-1::step-1::0a1b2c3d-0000-4000-8000-000000000001";
/** Whether a text is spoken: the app's live region carries it. */
const spoken = (text: string) =>
  waitFor(() =>
    expect(screen.getAllByText(text).some((node) => node.closest("[aria-live]"))).toBe(true)
  );

/** When a kept part was captured: two hours ago (inside the keeper's 24 h window), a minute per part. */
const KEPT_BASE = Math.floor(Date.now() / 60_000) * 60_000 - 2 * 60 * 60 * 1000;
const keptAt = (index: number) => KEPT_BASE + index * 60_000;
/** The part's file name as the run gets it: its capture time, with no characters a file system refuses. */
const keptName = (index: number) =>
  `recording-0a1b2c3d-0000-4000-8000-000000000001-seg0${index}-${new Date(keptAt(index)).toISOString().replace(/[:.]/g, "-")}.webm`;

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
    capturedAt: keptAt(index),
    interrupted: false,
    contract: {
      publishedFlowVersion: 4,
      inputFormat: "audio",
      maxFiles: 4,
      maxFileSizeBytes: null,
      acceptedMimetypes: ["audio/webm", "audio/mp4"]
    },
    streamed: false,
    // The signed-in person in `renderInApp`.
    userId: "user-1",
    ...overrides
  };
}

const audioContract = (live = false, partSeconds = 1_800, maxFiles = 4): RunContract =>
  makeContract({
    published_flow_version: 4,
    steps_requiring_input: [
      makeInput({
        step_id: "step-1",
        label: "Mötet",
        input_format: "audio",
        accepted_mimetypes: ["audio/webm", "audio/mp4"],
        max_files: maxFiles,
        max_duration_seconds: 7_200,
        max_recording_seconds: 7_200,
        recording_part_seconds: partSeconds
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

async function openDialog(contract: RunContract, userId = "user-1") {
  api.routes[CONTRACT] = () => ({ body: contract });
  api.routes[START] = () => ({ status: 201, body: { id: "run-1", status: "queued" } });
  const onStarted = vi.fn();
  renderInApp(<Harness onStarted={onStarted} />, {
    appContext: testAppContext({ user: { id: userId } })
  });
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

beforeEach(async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(null, { status: 204, headers: { [SESSION_GENERATION_HEADER]: "session-a" } })
      )
  );
  await initializeBrowserSession();
  // These tests exercise the recorder lifecycle, not a browser media decoder.
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:${crypto.randomUUID()}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  api.routes = {};
  FakeUpload.sent = [];
  FakeUpload.failNext = false;
  FakeUpload.failAll = false;
  FakeUpload.refuseNext = false;
  FakeUpload.refuseNamed = null;
  FakeSocket.instances = [];
  FakeNode.instances = [];
  microphone.mockReset();
  vi.stubGlobal("XMLHttpRequest", FakeUpload);
  device.db = memoryRecordings();
});

afterEach(() => {
  cleanup();
  api.stub.calls.length = 0;
  vi.restoreAllMocks();
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

  it("points a phone to its settings, not to an address bar icon or a microphone to plug in", async () => {
    setViewport("phone");
    installBrowser();
    microphone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    expect(
      await within(dialog).findByText(messages.flow_transcript_rec_permission_denied_touch)
    ).toBeTruthy();
    expect(within(dialog).queryByText(/adressfältet/)).toBeNull();
    cleanup();

    microphone.mockRejectedValue(new DOMException("none", "NotFoundError"));
    const second = await openDialog(audioContract());
    fireEvent.click(button(second.dialog, messages.flow_transcript_rec_start));
    expect(
      await within(second.dialog).findByText(messages.flow_transcript_rec_no_microphone_touch)
    ).toBeTruthy();
    expect(within(second.dialog).queryByText(/Anslut en mikrofon/)).toBeNull();
  });

  it("keeps focus in the recorder as its buttons trade places", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    const start = button(dialog, messages.flow_transcript_rec_start);
    start.focus();
    fireEvent.click(start);
    const pause = await within(dialog).findByRole("button", {
      name: messages.flow_transcript_rec_pause
    });
    await waitFor(() => expect(document.activeElement).toBe(pause));

    fireEvent.click(pause);
    const resume = await within(dialog).findByRole("button", {
      name: messages.flow_transcript_rec_resume
    });
    await waitFor(() => expect(document.activeElement).toBe(resume));

    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    const more = await within(dialog).findByRole("button", {
      name: messages.flow_transcript_rec_continue
    });
    await waitFor(() => expect(document.activeElement).toBe(more));
  });

  it("leaves focus where it is when someone is working elsewhere in the form", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    const pause = await within(dialog).findByRole("button", {
      name: messages.flow_transcript_rec_pause
    });
    const name = within(dialog).getByLabelText(
      new RegExp(`^${messages.flow_run_extras_run_label}`)
    );
    name.focus();
    fireEvent.click(pause);
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_resume });
    expect(document.activeElement).toBe(name);
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

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
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

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1", "file-2"], single_recording: true }
    });
  });

  it("numbers the next part after a part the core refused, so its copy on the device stays its own", async () => {
    installBrowser();
    grantMicrophone();
    const stored = vi.spyOn(device.db, "putPart");
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));

    // The second part is refused for good: it leaves the parts that stay on the form.
    FakeUpload.refuseNext = true;
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    );
    await within(dialog).findByText(/^Inspelning, del 2/);
    await waitFor(() => expect(stored).toHaveBeenCalledTimes(2));

    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_continue })
    );
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    );
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    expect(FakeUpload.sent[1]!.name).toMatch(/-seg02-/);
    await waitFor(() => expect(stored).toHaveBeenCalledTimes(3));
    expect(stored.mock.calls.map(([part]) => part.index)).toEqual([0, 1, 2]);
  });

  /**
   * Records `uploaded` parts, which upload, and one more, which the core refuses for good;
   * answers the refused part's remove button.
   */
  async function refuseLastPart(dialog: HTMLElement, uploaded = 1) {
    await recordAndStop(dialog);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    for (let part = 2; part <= uploaded; part++) {
      fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
      fireEvent.click(
        await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
      );
      await waitFor(() => expect(FakeUpload.sent).toHaveLength(part));
    }
    FakeUpload.refuseNext = true;
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    );
    // Refused: no upload left to stop, only the row to take off.
    return within(dialog).findByRole("button", {
      name: new RegExp(`^Ta bort Inspelning, del ${uploaded + 1}`)
    });
  }

  /** Closes the form with "Spara och fortsätt senare", opens it again and continues the recording. */
  async function saveAndContinue(dialog: HTMLElement) {
    fireEvent.click(button(dialog, messages.flow_transcript_save_later));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const again = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    fireEvent.click(
      await within(again).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    return again;
  }

  const FILES_FULL = /alla platser är använda\. Ta bort en fil om du vill spela in mer\./;
  const SLOT_HELD =
    /En del som inte kunde laddas upp håller en plats\. Ta bort delen för att frigöra platsen\. Spara den som fil först om du vill ha en kopia\.$/;

  it("keeps a part the core refused for good in its slot, so the saved recording can be continued", async () => {
    installBrowser();
    grantMicrophone();
    const stored = vi.spyOn(device.db, "putPart");
    const { dialog } = await openDialog(audioContract(false, 1_800, 2));
    await refuseLastPart(dialog);
    await waitFor(() => expect(stored).toHaveBeenCalledTimes(2));

    // Both parts are on the device: the step's two slots are used.
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    expect(await within(dialog).findByText(FILES_FULL)).toBeTruthy();
    expect(
      within(dialog).queryByRole("button", { name: messages.flow_transcript_rec_stop })
    ).toBeNull();
    expect(microphone).toHaveBeenCalledTimes(2);
    expect(stored).toHaveBeenCalledTimes(2);

    const again = await saveAndContinue(dialog);
    expect(await within(again).findByText(/^Inspelning, del 2/)).toBeTruthy();
    expect(within(again).getByText(/^Inspelning, del 1/)).toBeTruthy();
    expect(within(again).queryByText(messages.flow_transcript_resume_problem_title)).toBeNull();
  });

  it("says the refused part holds the slot the field counts as free, and records again once it is taken off the form", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract(false, 1_800, 5));
    const remove = await refuseLastPart(dialog, 4);
    // The field counts four of five: a refused row holds no place there.
    expect(within(dialog).getByText("Filer: 4 av 5")).toBeTruthy();
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    const full = await within(dialog).findByText(FILES_FULL);
    expect(full.textContent).toMatch(SLOT_HELD);

    fireEvent.click(remove);
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    expect(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    ).toBeTruthy();
  });

  it("records no part past the step's slots when a part is refused for good while the next records", async () => {
    installBrowser();
    grantMicrophone();
    const stored = vi.spyOn(device.db, "putPart");
    // One-second parts in a step that takes three files.
    const { dialog } = await openDialog(audioContract(false, 1, 3));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1), { timeout: 3_000 });
    // Part 2 is refused for good as it arrives, while part 3 records.
    FakeUpload.refuseNext = true;
    const ended = await within(dialog).findByText(SLOT_HELD, {}, { timeout: 6_000 });
    expect(ended.textContent?.startsWith(messages.flow_transcript_rec_ended_files)).toBe(true);
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_continue });
    await waitFor(() => expect(stored).toHaveBeenCalledTimes(3));
    expect(stored.mock.calls.map(([part]) => part.index)).toEqual([0, 1, 2]);
    expect(within(dialog).queryByText(/^Inspelning, del 4/)).toBeNull();

    const again = await saveAndContinue(dialog);
    expect(await within(again).findByText(/^Inspelning, del 3/)).toBeTruthy();
    expect(within(again).queryByText(messages.flow_transcript_resume_problem_title)).toBeNull();
  }, 12_000);

  it("asks to stop the recording before the run starts", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
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
    // It goes again by itself a few seconds later, or as soon as the browser is back online.
    expect(await within(dialog).findByText(/^Nytt försök kl\. \d\d:\d\d:\d\d/)).toBeTruthy();
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
    expect(socket.url).toBe("ws://localhost:3000/api/v1/live-transcription");
    act(() => {
      socket.open();
      socket.receive({ type: "ready", keeps_transcript: true, finish_within_seconds: 45 });
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
    // The same condition as before recording: no promise the text is used.
    expect(
      within(dialog).getByText(
        "Utkast. Flödet använder livetexten när den täcker hela inspelningen och kan kopplas till ljudfilen. Annars transkriberas inspelningen efteråt."
      )
    ).toBeTruthy();

    // The run waits for the final text, which names the stored transcript.
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
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
      "step-1": { file_ids: ["file-1"], streamed: true, live_transcript_id: "tr-1" }
    });
  });

  /** Opens the dialog with live text, records, and lets its socket say ready. */
  async function recordLive({
    keepsTranscript,
    partSeconds,
    finishWithinSeconds = 45
  }: {
    keepsTranscript: boolean;
    partSeconds?: number;
    finishWithinSeconds?: number;
  }) {
    installBrowser({ live: true });
    grantMicrophone();
    api.routes[LIVE] = () => ({
      status: 201,
      body: { ticket: "t0k3n", websocket_path: "/api/v1/live-transcription" }
    });
    const opened = await openDialog(audioContract(true, partSeconds));
    fireEvent.click(button(opened.dialog, messages.flow_transcript_rec_start));
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    act(() => {
      FakeSocket.instances[0]!.open();
      FakeSocket.instances[0]!.receive({
        type: "ready",
        keeps_transcript: keepsTranscript,
        finish_within_seconds: finishWithinSeconds
      });
      FakeNode.instances[0]!.frame(1);
    });
    return { ...opened, socket: FakeSocket.instances[0]! };
  }

  /** Starts the run, then delivers a final text naming a stored transcript, as a late core would. */
  function startThenFinalText(dialog: HTMLElement, socket: FakeSocket, id: string) {
    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    act(() => {
      socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: id });
    });
  }

  it("starts at once without a stored transcript when the core does not keep the live text", async () => {
    // The text is a preview: the run transcribes the streamed audio and says why.
    const { dialog, onStarted, socket } = await recordLive({ keepsTranscript: false });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    await waitFor(() => expect(socket.texts).toEqual([{ type: "stop" }]));

    // Nothing waits for the final text, so a late one cannot name the run's transcript.
    startThenFinalText(dialog, socket, "tr-1");
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1"], streamed: true }
    });
  });

  it("uses the stored transcript of a recording that was paused and went on", async () => {
    const { dialog, onStarted, socket } = await recordLive({ keepsTranscript: true });
    const node = FakeNode.instances[0]!;
    fireEvent.click(button(dialog, messages.flow_transcript_rec_pause));
    expect(node.port.postMessage).toHaveBeenLastCalledWith("pause");
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_resume })
    );
    expect(node.port.postMessage).toHaveBeenLastCalledWith("resume");
    act(() => node.frame(2));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    );
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    await waitFor(() => expect(socket.texts).toEqual([{ type: "stop", produced_samples: 3200 }]));

    startThenFinalText(dialog, socket, "tr-1");
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1"], streamed: true, live_transcript_id: "tr-1" }
    });
  });

  it("keeps the live text across the recording's parts and sends it with every part", async () => {
    // One-second parts: the recorder goes on in a new part a second in.
    const { dialog, onStarted, socket } = await recordLive({
      keepsTranscript: true,
      partSeconds: 1
    });
    const node = FakeNode.instances[0]!;
    await waitFor(() => expect(node.port.postMessage).toHaveBeenCalledWith("mark"), {
      timeout: 3_000
    });
    // Stopped well before the next part a second later.
    act(() => node.frame(2));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await within(dialog).findByText(/^Inspelning, del 2/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    await waitFor(() =>
      expect(socket.texts).toEqual([
        { type: "stop", produced_samples: 3200, part_start_samples: [1600] }
      ])
    );

    // The run waits for the final text of both parts, as for one.
    startThenFinalText(dialog, socket, "tr-1");
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": {
        file_ids: ["file-1", "file-2"],
        single_recording: true,
        streamed: true,
        live_transcript_id: "tr-1"
      }
    });
  });

  it("sends no stored transcript for a recording continued after a stop", async () => {
    const { dialog, onStarted, socket } = await recordLive({ keepsTranscript: true });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    act(() => {
      socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "tr-1" });
    });

    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_continue })
    );
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(2));
    const second = FakeSocket.instances[1]!;
    act(() => {
      second.open();
      second.receive({ type: "ready", keeps_transcript: true, finish_within_seconds: 45 });
      FakeNode.instances.at(-1)!.frame(2);
    });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 2/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    await waitFor(() => expect(second.texts).toEqual([{ type: "stop", produced_samples: 1600 }]));

    // Each part's text is whole, but neither stands for the recording.
    startThenFinalText(dialog, second, "tr-2");
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1", "file-2"], single_recording: true, streamed: true }
    });
  });

  it("sends the recording as streamed when the live text never started", async () => {
    installBrowser({ live: true });
    grantMicrophone();
    api.routes[LIVE] = () => ({ status: 503, body: { message: "Unavailable" } });
    const { dialog, onStarted } = await openDialog(audioContract(true));
    await recordAndStop(dialog);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1"], streamed: true }
    });
  });

  it("starts without the live transcript once the core's time for the final text has passed", async () => {
    const { dialog, onStarted, socket } = await recordLive({
      keepsTranscript: true,
      finishWithinSeconds: 0.05
    });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    await waitFor(() => expect(socket.close).toHaveBeenCalled());

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1"], streamed: true }
    });
  });

  it("keeps the stored transcript with the recording, so it goes with the run after a reload", async () => {
    const { dialog, onStarted, socket } = await recordLive({ keepsTranscript: true });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(socket.texts).toHaveLength(1));
    act(() => {
      socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "tr-1" });
    });
    await waitFor(() =>
      expect([...device.db.parts.values()].map((part) => part.liveTranscript)).toEqual([
        { id: "tr-1", parts: 1 }
      ])
    );

    // Closed and opened again: the recorder that heard it is gone, the device keeps it.
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_save_later })
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const again = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    fireEvent.click(
      await within(again).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await within(again).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    fireEvent.click(button(again, messages.flow_runs_summary_next));
    fireEvent.click(button(again, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-2"], streamed: true, live_transcript_id: "tr-1" }
    });
  });
});

describe("The recording's health", () => {
  it("shows the microphone's level while recording, and the part recorded last after", async () => {
    installBrowser({ live: true });
    grantMicrophone();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    expect(await within(dialog).findByText(messages.flow_transcript_rec_mic_label)).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    expect(within(dialog).queryByText(messages.flow_transcript_rec_mic_label)).toBeNull();
    fireEvent.click(button(dialog, messages.flow_transcript_rec_last_part));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(
      await within(dialog).findByRole("button", {
        name: messages.flow_transcript_rec_last_part_stop
      })
    ).toBeTruthy();
    await expectNoAxeViolations(document.body);
    // Recording again stops the preview.
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    expect(pause).toHaveBeenCalled();
    play.mockRestore();
    pause.mockRestore();
  });

  it("starts again by itself after the microphone went away, in the same recording", async () => {
    installBrowser();
    const track = grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });

    track.dispatchEvent(new Event("ended"));
    expect(
      await within(dialog).findByText(messages.flow_transcript_rec_restarting_device_lost)
    ).toBeTruthy();
    await within(dialog).findByText(/^Inspelning, del 1/);
    // A second later the microphone is asked again, without a click.
    await waitFor(() => expect(microphone).toHaveBeenCalledTimes(2), { timeout: 3_000 });
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    expect(within(dialog).queryByText(messages.flow_transcript_rec_restarting_title)).toBeNull();

    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 2/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    const [first, second] = FakeUpload.sent.map((file) => file.name.split("-seg")[0]);
    expect(second).toBe(first);
    expect(FakeUpload.sent[1]!.name).toMatch(/-seg01-/);
  });

  it("shows the recording's diagnostics and copies them, with nothing personal in them", async () => {
    installBrowser();
    grantMicrophone();
    const writeText = vi.fn<(text: string) => Promise<void>>(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));

    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_transcript_rec_diag_show })
    );
    const region = await within(dialog).findByRole("region", {
      name: messages.flow_transcript_rec_diag_label
    });
    const shown = JSON.parse(region.textContent ?? "{}");
    expect(shown.recorder).toMatchObject({ phase: "idle", ended: "manual" });
    expect(shown.recorder.format.requested).toBe("audio/webm;codecs=opus");
    expect(shown.parts).toEqual([
      expect.objectContaining({ index: 0, upload: "done", kept: "device" })
    ]);
    expect(shown.recorder.events.map((entry: { event: string }) => entry.event)).toContain(
      "part_handed_over"
    );
    await expectNoAxeViolations(document.body);

    fireEvent.click(button(dialog, messages.flow_transcript_rec_diag_copy));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0]![0];
    expect(JSON.parse(copied).parts).toHaveLength(1);
    // No step name, file name, recording id or file id.
    const sessionId = FakeUpload.sent[0]!.name.split("-seg")[0]!.replace("recording-", "");
    for (const personal of ["Mötet", "Inspelning, del", "recording-", sessionId, "file-1"]) {
      expect(copied).not.toContain(personal);
    }
  });

  it("says how large the part is while recording, and how much more fits after a stop", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    expect(within(dialog).getByText(/Den kan vara upp till 2 h lång\./)).toBeTruthy();
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    // Opus at 24 kbit/s, against the step's 10 MB per file.
    expect(
      within(dialog).getByText(/^Delen är .+ av högst 10\sMB, ungefär 10,3\sMB per timme\.$/)
    ).toBeTruthy();
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    // Two hours less the room kept below the limit and the next part's handover.
    expect(within(dialog).getByText(/Du kan spela in 1 h 58 min till\./)).toBeTruthy();
    expect(within(dialog).queryByText(/^Delen är/)).toBeNull();
  });

  it("says how long one file holds where the step sets no length", async () => {
    installBrowser();
    const contract = audioContract();
    const input = contract.steps_requiring_input![0]!;
    contract.steps_requiring_input = [
      { ...input, max_duration_seconds: null, max_recording_seconds: null }
    ];
    const { dialog } = await openDialog(contract);
    // 10 MB at 24 kbit/s.
    expect(
      within(dialog).getByText(/En fil på 10\sMB rymmer ungefär 58 min med den här webbläsaren\./)
    ).toBeTruthy();
  });

  it("keeps recording through outages at the parts' changes while the parts are kept on the device", async () => {
    installBrowser();
    grantMicrophone();
    FakeUpload.failAll = true;
    const { dialog } = await openDialog(audioContract(false, 1, 10));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    // Two parts' uploads fail at two changes of part, and a third part follows.
    expect(
      await within(dialog).findByText(/^Inspelning, del 3/, {}, { timeout: 6_000 })
    ).toBeTruthy();
    expect(within(dialog).getAllByText(/^Nytt försök kl\./).length).toBeGreaterThanOrEqual(2);
    expect(button(dialog, messages.flow_transcript_rec_stop)).toBeTruthy();
    expect(within(dialog).queryByText(messages.flow_transcript_rec_ended_backlog)).toBeNull();
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_continue });
  }, 10_000);

  it("records more after several parts failed to upload, while they are kept on the device", async () => {
    installBrowser();
    grantMicrophone();
    FakeUpload.failAll = true;
    const { dialog } = await openDialog(audioContract());
    for (let part = 1; part <= 3; part += 1) {
      fireEvent.click(
        button(
          dialog,
          part === 1 ? messages.flow_transcript_rec_start : messages.flow_transcript_rec_continue
        )
      );
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
      fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
      await within(dialog).findByText(new RegExp(`^Inspelning, del ${part}`));
      await waitFor(() =>
        expect(within(dialog).getAllByText(/^Nytt försök kl\./)).toHaveLength(part)
      );
    }
    await waitFor(() => expect(device.db.parts.size).toBe(3));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    expect(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    ).toBeTruthy();
    expect(within(dialog).queryByText(messages.flow_transcript_rec_backlog_full)).toBeNull();
    expect(microphone).toHaveBeenCalledTimes(4);
  });

  it("does not record more while earlier parts kept only in this tab wait for their upload", async () => {
    installBrowser();
    grantMicrophone();
    FakeUpload.failAll = true;
    // The device's storage is full: each part lives only in this tab.
    device.db.putPart = () => Promise.reject(new DOMException("full", "QuotaExceededError"));
    const { dialog } = await openDialog(audioContract());
    for (let part = 1; part <= 3; part += 1) {
      fireEvent.click(
        button(
          dialog,
          part === 1 ? messages.flow_transcript_rec_start : messages.flow_transcript_rec_continue
        )
      );
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
      fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
      await within(dialog).findByText(new RegExp(`^Inspelning, del ${part}`));
      await waitFor(() =>
        expect(within(dialog).getAllByText(/^Nytt försök kl\./)).toHaveLength(part)
      );
    }
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    expect(await within(dialog).findByText(messages.flow_transcript_rec_backlog_full)).toBeTruthy();
    expect(microphone).toHaveBeenCalledTimes(3);
  });
});

describe("Keeping a recording on the device", () => {
  it("sends a streamed recording kept from an earlier visit as streamed, with no transcript it did not keep", async () => {
    installBrowser();
    // The page went away before the live text came, or its id could not be kept.
    await device.db.putPart(keptPart(0, { streamed: true }));
    await device.db.putPart(keptPart(1, { streamed: true, interrupted: true }));
    const { dialog, onStarted } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1", "file-2"], single_recording: true, streamed: true }
    });
  });

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
    expect(FakeUpload.sent.map((file) => file.name)).toEqual([keptName(0), keptName(1)]);

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

    fireEvent.click(button(dialog, messages.flow_runs_summary_next));
    fireEvent.click(button(dialog, messages.flow_runs_start_submit));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(startBody()?.step_inputs).toEqual({
      "step-1": { file_ids: ["file-1", "file-2", "file-3"], single_recording: true }
    });
    // The run took the recording: nothing of it stays on the device.
    await waitFor(() => expect(device.db.parts.size).toBe(0));
  });

  /**
   * Continues a kept recording of a first part of an hour, which uploads, and a second of
   * `refusedMinutes`, which the core refuses for good; answers the refused part's remove button.
   */
  async function continueWithRefusedPart(refusedMinutes: number, uploadedMinutes = 60) {
    installBrowser();
    grantMicrophone();
    FakeUpload.refuseNamed = /-seg01-/;
    await device.db.putPart(keptPart(0, { durationMs: uploadedMinutes * 60_000 }));
    await device.db.putPart(keptPart(1, { durationMs: refusedMinutes * 60_000 }));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    const remove = await within(dialog).findByRole("button", {
      name: /^Ta bort Inspelning, del 2/
    });
    return { dialog, remove };
  }

  it("counts a part the core refused for good in the recording's length, and says so", async () => {
    // Two hours less a minute's room and the handovers: an hour and 59 minutes fill it.
    const { dialog } = await continueWithRefusedPart(59);
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    const ended = await within(dialog).findByText(
      new RegExp(`^${messages.flow_transcript_rec_ended_length.replace(/\./g, "\\.")}`),
      {},
      { timeout: 2_000 }
    );
    expect(ended.textContent).toMatch(
      /En del som inte kunde laddas upp räknas i inspelningens längd\. Ta bort delen för att få tillbaka tiden\. Spara den som fil först om du vill ha en kopia\.$/
    );
    // A manual start is not held back: the part it began, under a second, is handed over.
    expect(await within(dialog).findByText(/^Inspelning, del 3 \(00:0[01]\)/)).toBeTruthy();
  });

  it("says only that the length is reached when no refused part takes time", async () => {
    installBrowser();
    grantMicrophone();
    await device.db.putPart(keptPart(0, { durationMs: 60 * 60_000 }));
    await device.db.putPart(keptPart(1, { durationMs: 59 * 60_000 }));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    expect(
      await within(dialog).findByText(
        messages.flow_transcript_rec_ended_length,
        {},
        { timeout: 2_000 }
      )
    ).toBeTruthy();
  });

  it("gives the time back once the refused part is taken off the form", async () => {
    const { dialog, remove } = await continueWithRefusedPart(59);
    fireEvent.click(remove);
    // Two hours less a minute's room, a handover and the hour uploaded.
    expect(await within(dialog).findByText(/Du kan spela in 58 min till\./)).toBeTruthy();
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    // Past the recorder's first check of the time left: still recording.
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(button(dialog, messages.flow_transcript_rec_stop)).toBeTruthy();
    expect(within(dialog).queryByText(messages.flow_transcript_rec_ended_title)).toBeNull();
  });

  it("says the time left as the recorder counts it, a refused part included", async () => {
    const { dialog } = await continueWithRefusedPart(30);
    // Two hours less a minute's room, two handovers, the hour uploaded and the refused half hour.
    expect(await within(dialog).findByText(/Du kan spela in 28 min till\./)).toBeTruthy();
  });

  it("records more after continuing a kept recording whose parts have not uploaded yet", async () => {
    installBrowser();
    grantMicrophone();
    FakeUpload.failAll = true;
    for (const index of [0, 1, 2]) await device.db.putPart(keptPart(index));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await within(dialog).findByText(/^Inspelning, del 3/);
    await waitFor(() => expect(within(dialog).getAllByText(/^Nytt försök kl\./)).toHaveLength(3));

    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    expect(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    ).toBeTruthy();
    expect(within(dialog).queryByText(messages.flow_transcript_rec_backlog_full)).toBeNull();
  });

  it("offers a kept recording only to the person who recorded it", async () => {
    installBrowser();
    grantMicrophone();
    await device.db.putPart(keptPart(0, { userId: "user-2" }));
    await device.db.putPart(keptPart(1, { userId: "user-2" }));
    // Someone else signs in on the same browser: nothing to continue or throw away.
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    expect(within(dialog).queryByText(messages.flow_transcript_resume_title)).toBeNull();
    // Their own recording, thrown away, leaves the other person's as it was.
    fireEvent.click(button(dialog, messages.flow_transcript_discard));
    const confirm = await screen.findByRole("alertdialog", {
      name: messages.flow_transcript_discard_title
    });
    fireEvent.click(
      within(confirm).getByRole("button", { name: messages.flow_transcript_discard })
    );
    await waitFor(() => expect(within(dialog).queryByText(/^Inspelning, del/)).toBeNull());
    expect([...device.db.parts.values()].map((part) => part.userId)).toEqual(["user-2", "user-2"]);
    expect(FakeUpload.sent.map((file) => file.name)).not.toContain(keptName(0));
    cleanup();

    // The person who recorded it signs in again and gets it back.
    const again = await openDialog(audioContract(), "user-2");
    expect(
      await within(again.dialog).findByText(messages.flow_transcript_resume_title)
    ).toBeTruthy();
  });

  it("asks the browser to keep the device's storage once the microphone is given, once per page", async () => {
    installBrowser();
    grantMicrophone();
    const stream = await microphone();
    let give = () => {};
    microphone.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          give = () => resolve(stream);
        })
    );
    // Never answered: the recording does not wait for it.
    const persist = vi.fn(() => new Promise<boolean>(() => undefined));
    Object.defineProperty(navigator, "storage", { configurable: true, value: { persist } });
    onTestFinished(() => {
      Reflect.deleteProperty(navigator, "storage");
    });
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await waitFor(() => expect(microphone).toHaveBeenCalledTimes(2));
    // Not while the browser asks for the microphone: one question at a time.
    expect(persist).not.toHaveBeenCalled();
    act(() => give());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop })
    );
    await within(dialog).findByText(/^Inspelning, del 1/);
    expect(persist).toHaveBeenCalledTimes(1);

    // Once for the page, not at every start or in every form.
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    cleanup();
    const again = await openDialog(audioContract());
    await recordAndStop(again.dialog);
    expect(persist).toHaveBeenCalledTimes(1);
  });

  it("records as usual where the browser cannot keep its storage, or refuses to", async () => {
    installBrowser();
    grantMicrophone();
    Object.defineProperty(navigator, "storage", { configurable: true, value: undefined });
    onTestFinished(() => {
      Reflect.deleteProperty(navigator, "storage");
    });
    const first = await openDialog(audioContract());
    expect(await recordAndStop(first.dialog)).toBeTruthy();
    cleanup();

    const persist = vi.fn(() => Promise.reject(new DOMException("denied", "NotAllowedError")));
    Object.defineProperty(navigator, "storage", { configurable: true, value: { persist } });
    const second = await openDialog(audioContract());
    expect(await recordAndStop(second.dialog)).toBeTruthy();
    expect(persist).toHaveBeenCalledTimes(1);
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

    // The closed form let go of it.
    await waitFor(() => expect(browserLocks.heldNames()).toEqual([]));

    // Opened again in the same tab, the form offers it, and goes on with it.
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const again = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    expect(await within(again).findByText(messages.flow_transcript_resume_title)).toBeTruthy();
    fireEvent.click(button(again, messages.flow_transcript_resume_continue));
    expect(await within(again).findByText(/^Inspelning, del 1/)).toBeTruthy();
    expect(within(again).queryByText(messages.flow_transcript_resume_problem_title)).toBeNull();
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
  });

  it("does not continue a kept recording another tab has open: no rows, no upload", async () => {
    installBrowser();
    await device.db.putPart(keptPart(0));
    browserLocks.holdElsewhere(HOLD);
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    const refused = messages.flow_transcript_resume_open_elsewhere;
    expect(await within(dialog).findByText(refused)).toBeTruthy();
    await spoken(refused);
    expect(within(dialog).queryByText(/^Inspelning, del/)).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(FakeUpload.sent).toHaveLength(0);
    expect(device.db.parts.size).toBe(1);

    // Once the other tab has let go, it continues here.
    browserLocks.releaseElsewhere(HOLD);
    fireEvent.click(button(dialog, messages.flow_transcript_resume_continue));
    expect(await within(dialog).findByText(/^Inspelning, del 1/)).toBeTruthy();
  });

  it("does not discard a kept recording another tab has open, and removes nothing", async () => {
    installBrowser();
    await device.db.putPart(keptPart(0));
    browserLocks.holdElsewhere(HOLD);
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_discard })
    );
    const refused = messages.flow_transcript_resume_discard_open_elsewhere;
    expect(await within(dialog).findByText(refused)).toBeTruthy();
    await spoken(refused);
    expect(device.db.parts.size).toBe(1);

    // Once the other tab has let go, it can be discarded here.
    browserLocks.releaseElsewhere(HOLD);
    fireEvent.click(button(dialog, messages.flow_transcript_resume_discard));
    await waitFor(() => expect(device.db.parts.size).toBe(0));
    expect(browserLocks.isHeld(HOLD)).toBe(false);
  });

  it("says the recording could not be read, not that it is open elsewhere, when asking to hold it fails", async () => {
    installBrowser();
    await device.db.putPart(keptPart(0));
    browserLocks.failRequests("eneo-flow-recording-holder:");
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(
      await within(dialog).findByText(messages.flow_transcript_resume_read_failed)
    ).toBeTruthy();
    expect(within(dialog).queryByText(/^Inspelning, del/)).toBeNull();
    expect(device.db.parts.size).toBe(1);
  });

  it("holds the recording it records, and no recording after a start the microphone refused", async () => {
    installBrowser();
    microphone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(button(dialog, messages.flow_transcript_rec_start));
    await within(dialog).findByText(messages.flow_transcript_rec_problem_title);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(browserLocks.heldNames()).toEqual([]);

    grantMicrophone();
    await recordAndStop(dialog);
    await waitFor(() =>
      expect(browserLocks.heldNames().filter((name) => name.includes("-holder:"))).toHaveLength(1)
    );
  });

  it("never gives the number of a part left unfinished to a new part, also after a row is removed", async () => {
    installBrowser();
    grantMicrophone();
    await device.db.putPart(keptPart(0));
    await device.db.putPart(keptPart(1));
    const journal = { ...keptPart(2), lastChunkAt: keptAt(2) };
    await device.db.putJournal(journal);
    await device.db.appendChunk(journal, 0, {
      blob: new Blob(["cut"], { type: "audio/webm" }),
      recordedMs: 1_000,
      at: keptAt(2)
    });
    // A tab left part 3 mid-recording, and its chunks cannot be read now: it stays a journal.
    vi.spyOn(device.db, "readChunks").mockRejectedValue(new Error("blocked"));
    const { dialog } = await openDialog(audioContract());
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(await within(dialog).findByText("Inspelning, del 2 (00:30)")).toBeTruthy();
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));

    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: /^Ta bort Inspelning, del 4/ })
    );
    await waitFor(() => expect(within(dialog).queryByText(/^Inspelning, del 4/)).toBeNull());

    // Recorded again with that row gone, the new part still takes a number over the journal's.
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 4/);
    await waitFor(() =>
      expect(device.db.parts.has(`flow-1::step-1::${keptPart(0).sessionId}::0003`)).toBe(true)
    );
    expect(device.db.parts.has(`flow-1::step-1::${keptPart(0).sessionId}::0002`)).toBe(false);
    expect(device.db.journals.size).toBe(1);
  });

  it("puts a refused offer last, with its refusal shown only beside it", async () => {
    installBrowser();
    grantMicrophone();
    const other = "0a1b2c3d-0000-4000-8000-000000000002";
    // The newest recording, offered first, has two parts; an older one has one.
    await device.db.putPart(keptPart(0));
    await device.db.putPart(keptPart(1));
    await device.db.putPart(keptPart(0, { sessionId: other, capturedAt: keptAt(-5) }));
    browserLocks.holdElsewhere(HOLD);
    browserLocks.holdElsewhere(`eneo-flow-recording-holder:flow-1::step-1::${other}`);
    const { dialog } = await openDialog(audioContract());
    const refused = messages.flow_transcript_resume_open_elsewhere;
    expect(await within(dialog).findByText(/består av 2 delar/)).toBeTruthy();

    // Refused, the newest goes last: the older one is offered, without the first one's refusal.
    fireEvent.click(button(dialog, messages.flow_transcript_resume_continue));
    expect(await within(dialog).findByText(/består av en del/)).toBeTruthy();
    expect(within(dialog).queryByText(refused)).toBeNull();
    await spoken(refused);

    // Every offer refused: the first refused is offered again, with its own refusal.
    fireEvent.click(button(dialog, messages.flow_transcript_resume_continue));
    expect(await within(dialog).findByText(/består av 2 delar/)).toBeTruthy();
    expect(within(dialog).getByText(refused)).toBeTruthy();

    // A new recording can start meanwhile, and the refused one is tried again once the other
    // tab let go.
    await recordAndStop(dialog);
    browserLocks.releaseElsewhere(HOLD);
    fireEvent.click(button(dialog, messages.flow_transcript_resume_continue));
    expect(await within(dialog).findByText("Inspelning, del 2 (00:30)")).toBeTruthy();

    // "Inte nu" does as before: the prompt goes.
    fireEvent.click(button(dialog, messages.flow_transcript_resume_not_now));
    await waitFor(() =>
      expect(within(dialog).queryByText(messages.flow_transcript_resume_title)).toBeNull()
    );
  });

  it("takes nothing over when the form closes while Fortsätt waits, in the app's strict mode", async () => {
    installBrowser();
    await device.db.putPart(keptPart(0));
    api.routes[CONTRACT] = () => ({ body: audioContract() });
    renderInApp(
      <StrictMode>
        <Harness onStarted={vi.fn()} />
      </StrictMode>,
      { appContext: testAppContext({ user: { id: "user-1" } }) }
    );
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    const resume = await within(dialog).findByRole("button", {
      name: messages.flow_transcript_resume_continue
    });
    const grant = browserLocks.deferGrants();
    fireEvent.click(resume);
    fireEvent.click(button(dialog, messages.cancel));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    grant();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(FakeUpload.sent).toHaveLength(0);
    expect(browserLocks.heldNames()).toEqual([]);
    expect(device.db.parts.size).toBe(1);

    // The form opened again in strict mode still continues it.
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const again = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    fireEvent.click(
      await within(again).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(await within(again).findByText(/^Inspelning, del 1/)).toBeTruthy();
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
  });

  it("throws the whole recording away after asking, its uploads and what the device kept", async () => {
    installBrowser();
    grantMicrophone();
    const { dialog } = await openDialog(audioContract());
    await recordAndStop(dialog);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 2/);
    await waitFor(() => expect(device.db.parts.size).toBe(2));

    fireEvent.click(button(dialog, messages.flow_transcript_discard));
    const confirm = await screen.findByRole("alertdialog", {
      name: messages.flow_transcript_discard_title
    });
    await expectNoAxeViolations(document.body);
    fireEvent.click(
      within(confirm).getByRole("button", { name: messages.flow_transcript_discard })
    );

    await waitFor(() => expect(within(dialog).queryByText(/^Inspelning, del/)).toBeNull());
    expect(device.db.parts.size).toBe(0);
    const deleted = api.stub.calls
      .filter((call) => call.method === "DELETE")
      .map((call) => call.init);
    expect(deleted).toEqual([
      { params: { path: { id: "flow-1", file_id: "file-1" } } },
      { params: { path: { id: "flow-1", file_id: "file-2" } } }
    ]);
    // A new recording starts from the first part, and focus waits on its button.
    const start = button(dialog, messages.flow_transcript_rec_start);
    expect(document.activeElement).toBe(start);
    expect(
      within(dialog).queryByRole("button", { name: messages.flow_transcript_discard })
    ).toBeNull();
    fireEvent.click(start);
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await within(dialog).findByText(/^Inspelning, del 1/);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(3));
    expect(FakeUpload.sent[2]!.name).toMatch(/-seg00-/);
    expect(FakeUpload.sent[2]!.name.split("-seg")[0]).not.toBe(
      FakeUpload.sent[0]!.name.split("-seg")[0]
    );
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

describe("the live text", () => {
  const listening = (...texts: string[]): LiveSnapshot => ({
    status: "listening",
    pieces: texts.map((text, id) => ({ id, text })),
    paused: false,
    finishing: false,
    errorCode: null
  });
  /** A box 100 px high whose text is `height` px; jsdom lays nothing out. */
  function layOut(box: HTMLElement, height: { current: number }) {
    // ScrollableArea makes a box that overflows a tab stop once it has measured it.
    box.tabIndex = 0;
    Object.defineProperty(box, "clientHeight", { configurable: true, get: () => 100 });
    Object.defineProperty(box, "scrollHeight", { configurable: true, get: () => height.current });
    box.scrollTo = vi.fn(({ top }: ScrollToOptions) => {
      box.scrollTop = top ?? 0;
    }) as typeof box.scrollTo;
  }
  function scrollTo(box: HTMLElement, top: number) {
    box.scrollTop = top;
    fireEvent.scroll(box);
  }
  const latest = () => screen.queryByRole("button", { name: messages.flow_transcript_live_latest });

  it("keeps to the newest text until the person scrolls up, and goes back to it on request", () => {
    const height = { current: 300 };
    const { rerender } = renderInApp(<LiveText snapshot={listening("Ett")} />);
    const box = screen.getByRole("region", { name: messages.flow_transcript_live_heading });
    layOut(box, height);

    rerender(<LiveText snapshot={listening("Ett", "Två")} />);
    expect(box.scrollTop).toBe(300);
    scrollTo(box, 300);
    expect(latest()).toBeNull();

    // Scrolling up to read lets go of the end: new text no longer moves the box.
    scrollTo(box, 120);
    height.current = 400;
    rerender(<LiveText snapshot={listening("Ett", "Två", "Tre")} />);
    expect(box.scrollTop).toBe(120);
    const show = latest();
    expect(show).toBeTruthy();

    fireEvent.click(show!);
    expect(box.scrollTo).toHaveBeenCalledWith({ top: 400, behavior: "smooth" });
    expect(document.activeElement).toBe(box);
    expect(latest()).toBeNull();
    height.current = 500;
    rerender(<LiveText snapshot={listening("Ett", "Två", "Tre", "Fyra")} />);
    expect(box.scrollTop).toBe(500);
  });

  it("follows again when the person scrolls back down to the end themselves", () => {
    const height = { current: 300 };
    renderInApp(<LiveText snapshot={listening("Ett")} />);
    const box = screen.getByRole("region", { name: messages.flow_transcript_live_heading });
    layOut(box, height);
    scrollTo(box, 200);
    scrollTo(box, 50);
    expect(latest()).toBeTruthy();
    // Within a line of the end counts as the end.
    scrollTo(box, 180);
    expect(latest()).toBeNull();
  });

  it("jumps without a smooth scroll when the person asks for less motion", () => {
    const media = window.matchMedia;
    const reduce = vi.spyOn(window, "matchMedia").mockImplementation((query: string) => {
      const list = media(query);
      if (query === "(prefers-reduced-motion: reduce)") {
        Object.defineProperty(list, "matches", { get: () => true });
      }
      return list;
    });
    onTestFinished(() => reduce.mockRestore());
    const height = { current: 300 };
    renderInApp(<LiveText snapshot={listening("Ett")} />);
    const box = screen.getByRole("region", { name: messages.flow_transcript_live_heading });
    layOut(box, height);
    scrollTo(box, 200);
    scrollTo(box, 50);
    fireEvent.click(latest()!);
    expect(box.scrollTo).toHaveBeenCalledWith({ top: 300, behavior: "auto" });
  });
});
