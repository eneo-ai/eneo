// @vitest-environment jsdom
/**
 * Loss catalogue: what the current code keeps or loses, byte for byte, in the
 * sequences review findings reproduced against the "one tab holds a kept
 * recording" cuts. Every test is green on the current code: "base loses" is a
 * loss a fix must remove, "base keeps" one no fix may introduce.
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createElement, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initializeBrowserSession, SESSION_GENERATION_HEADER } from "@/lib/api/refusal";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow } from "../../../flow-fixtures";
import { makeContract, makeInput } from "../../run-fixtures";
import type { RunContract } from "../../runs-api";
import {
  RecordingKeeper,
  resumeRefusal,
  storedPartFile,
  type JournalPart
} from "../recording-keeper";
import {
  memoryRecordings,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type StoredPart
} from "../recording-store";
import { fakeLocks } from "./catalog-locks";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../../../editor/testing/fixtures").apiStub>
}));
const device = vi.hoisted(() => ({
  db: null as unknown as ReturnType<typeof import("../recording-store").memoryRecordings>
}));
vi.mock("../recording-store", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../recording-store")>()),
  indexedDbRecordings: () => device.db
}));
vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("../../../editor/testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { StartRunDialog } from "../../start-run-dialog";

/** A blob's bytes as text; jsdom's Blob may lack `text()`. */
function bytes(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

/** Every part on the device as `index:bytes`, by session, in key order. */
async function onDevice(db: ReturnType<typeof memoryRecordings>) {
  const out: Record<string, string[]> = {};
  for (const key of [...db.parts.keys()].sort()) {
    const part = db.parts.get(key)!;
    (out[part.sessionId] ??= []).push(`${part.index}:${await bytes(part.blob)}`);
  }
  return out;
}

/** A gate a controlled promise opens. */
function gate() {
  let open = () => {};
  const opened = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { opened, open };
}

// ---------------------------------------------------------------------------
// The keeper, the journal and the store, driven as the form drives them.
// ---------------------------------------------------------------------------

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 3,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};
const T0 = Date.UTC(2026, 9, 22, 8, 0, 0);
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function seedPart(
  sessionId: string,
  index: number,
  text: string,
  capturedAt = T0 + index * 60_000
) {
  return {
    flowId: "flow-1",
    stepId: "step-1",
    sessionId,
    index,
    blob: new Blob([text], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 30_000,
    capturedAt,
    interrupted: false,
    contract: CONTRACT,
    streamed: false,
    userId: "user-a"
  } satisfies StoredPart;
}

/** A finished part as the recorder hands it to `keepPart`. */
const finished = (
  sessionId: string,
  index: number,
  text: string,
  capturedAt = T0 + index * 60_000
) => ({
  sessionId,
  index,
  blob: new Blob([text], { type: "audio/webm" }),
  mimeType: "audio/webm",
  durationMs: 30_000,
  capturedAt,
  contract: CONTRACT,
  streamed: false
});

/** The form's next part number: one past every recorded row of the recording on its form. */
const nextIndex = (rows: readonly { index: number }[]) =>
  rows.reduce((next, row) => Math.max(next, row.index + 1), 0);

describe("loss catalogue: keeper, journal and store", () => {
  // cut review A F15: a fix must keep two lockless tabs on distinct part numbers after a removed row, so both new parts survive.
  it("base keeps: two tabs without Web Locks number past their own rows after one removes a row, and both new parts survive", async () => {
    const db = memoryRecordings();
    await db.putPart(seedPart("rec-1", 0, "seed-0"));
    await db.putPart(seedPart("rec-1", 1, "seed-1"));
    const tabA = new RecordingKeeper("flow-1", "user-a", db, null, () => T0);
    const tabB = new RecordingKeeper("flow-1", "user-a", db, null, () => T0);

    // Both continue the stored parts 0 and 1.
    const rowsA = await tabA.readSession("step-1", "rec-1");
    tabA.adopt("step-1", rowsA);
    const rowsB = await tabB.readSession("step-1", "rec-1");
    tabB.adopt("step-1", rowsB);

    // A takes row 1 off its form; B keeps both rows.
    await tabA.forgetPart("step-1", "rec-1", 1);
    const formA = rowsA.filter((row) => row.index !== 1);

    const indexA = nextIndex(formA);
    const indexB = nextIndex(rowsB);
    expect([indexA, indexB]).toEqual([1, 2]);
    expect(await tabA.keepPart("step-1", finished("rec-1", indexA, "AAAA"))).toBe("device");
    expect(await tabB.keepPart("step-1", finished("rec-1", indexB, "BBBB"))).toBe("device");

    expect(await onDevice(db)).toEqual({ "rec-1": ["0:seed-0", "1:AAAA", "2:BBBB"] });
  });

  // cut review A findings (the three-file case): a fix must keep the part a closed tab left unfinished when another tab continues the recording and records the same number.
  it("base loses: a part a closed tab left unfinished is overwritten when another tab continues the recording", async () => {
    const db = memoryRecordings();
    await db.putPart(seedPart("rec-1", 0, "part0"));
    await db.putPart(seedPart("rec-1", 1, "part1"));
    // Tab A records part 2 and closes mid-part: its journal stays, its own browser lock goes with it.
    const locksA = fakeLocks();
    const tabA = new RecordingKeeper("flow-1", "user-a", db, locksA.locks, () => T0 + 120_000);
    const journalA = tabA.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const partA: JournalPart = {
      sessionId: "rec-1",
      index: 2,
      mimeType: "audio/webm",
      capturedAt: T0 + 120_000
    };
    journalA.begin(partA);
    journalA.append(partA, new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    await settle();
    expect(db.journals.size).toBe(1);

    // Tab B's form opens while A still holds the part: the scan leaves A's journal alone.
    const locksB = fakeLocks();
    const lockName = "eneo-flow-recording:flow-1::step-1::rec-1::0002";
    locksB.holdElsewhere(lockName);
    const tabB = new RecordingKeeper("flow-1", "user-a", db, locksB.locks, () => T0 + 180_000);
    const offered = await tabB.scan("step-1");
    expect(offered.saved.map((saved) => [saved.sessionId, saved.parts])).toEqual([["rec-1", 2]]);
    // A's tab is gone; B presses Continue on the offer it already shows.
    locksB.releaseElsewhere(lockName);
    const rows = await tabB.readSession("step-1", "rec-1");
    expect(resumeRefusal(CONTRACT, rows)).toBeNull();
    tabB.adopt("step-1", rows);

    // B records its next part, numbered past its rows: the same number as A's unfinished part.
    const index = nextIndex(rows);
    expect(index).toBe(2);
    const journalB = tabB.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    const partB: JournalPart = {
      sessionId: "rec-1",
      index,
      mimeType: "audio/webm",
      capturedAt: T0 + 180_000
    };
    journalB.begin(partB);
    journalB.append(partB, new Blob(["BBBB"], { type: "audio/webm" }), 1_000);
    await settle();
    expect(await tabB.keepPart("step-1", finished("rec-1", index, "BBBB", T0 + 180_000))).toBe(
      "device"
    );

    // The form opens again: nothing is left to rebuild.
    const reopened = new RecordingKeeper(
      "flow-1",
      "user-a",
      db,
      fakeLocks().locks,
      () => T0 + 240_000
    );
    const { saved } = await reopened.scan("step-1");
    expect(saved.map((recording) => recording.parts)).toEqual([3]);
    expect(await onDevice(db)).toEqual({ "rec-1": ["0:part0", "1:part1", "2:BBBB"] });
    expect(db.journals.size).toBe(0);
    expect(db.chunks.size).toBe(0);
  });

  // cut review A F16 (also F17): a fix must leave a recording whose discard failed on the device and reachable from another tab.
  it("base keeps: a discard whose delete fails leaves the recording on the device, and another tab can still continue it", async () => {
    const db = memoryRecordings();
    const tabA = new RecordingKeeper("flow-1", "user-a", db, fakeLocks().locks, () => T0);
    expect(await tabA.keepPart("step-1", finished("rec-1", 0, "KEPT"))).toBe("device");
    vi.spyOn(db, "deleteSession").mockRejectedValueOnce(new Error("blocked"));

    expect(await tabA.forgetSession("step-1", "rec-1")).toBe(false);

    const tabB = new RecordingKeeper("flow-1", "user-a", db, fakeLocks().locks, () => T0 + 60_000);
    expect((await tabB.scan("step-1")).saved.map((saved) => saved.sessionId)).toEqual(["rec-1"]);
    const rows = await tabB.readSession("step-1", "rec-1");
    expect(await Promise.all(rows.map((row) => bytes(storedPartFile(row))))).toEqual(["KEPT"]);
    expect(await onDevice(db)).toEqual({ "rec-1": ["0:KEPT"] });
  });

  // final review F19: a fix must still hand the pressed recording's bytes to the form when another tab's expiry cleanup is under way as Continue is pressed.
  it("base keeps: Continue reads the parts before another tab's expiry cleanup deletes them, so the form gets the audio (the device copy is gone)", async () => {
    const db = memoryRecordings();
    // One minute before the day runs out for this form.
    const capturedAt = T0 - RECORDING_TTL_MS + 60_000 - 30_000;
    await db.putPart(seedPart("rec-solo", 0, "ONLY-SOLO", capturedAt));
    const form = new RecordingKeeper("flow-1", "user-a", db, fakeLocks().locks, () => T0);
    expect((await form.scan("step-1")).saved.map((saved) => saved.sessionId)).toEqual(["rec-solo"]);

    // Another tab's scan, with its clock past the day, has decided to delete and is about to.
    const deleteSession = db.deleteSession.bind(db);
    const held = gate();
    const deleting = vi.spyOn(db, "deleteSession").mockImplementationOnce(async (...args) => {
      await held.opened;
      return deleteSession(...args);
    });
    const other = new RecordingKeeper("flow-1", "user-a", db, null, () => T0 + 120_000);
    const scanning = other.scan("step-1");
    await vi.waitFor(() => expect(deleting).toHaveBeenCalled());

    // The person presses Continue: the form reads at once.
    const rows = await form.readSession("step-1", "rec-solo");
    expect(resumeRefusal(CONTRACT, rows)).toBeNull();
    form.adopt("step-1", rows);
    const files = rows.map(storedPartFile);

    held.open();
    await scanning;
    expect(await Promise.all(files.map(bytes))).toEqual(["ONLY-SOLO"]);
    expect(await onDevice(db)).toEqual({});
    // The form still counts the part as kept on the device.
    expect(form.keeping("step-1", "rec-solo", 0)).toBe("device");
  });
});

// ---------------------------------------------------------------------------
// The start form, rendered as run-recorder.test.tsx renders it.
// ---------------------------------------------------------------------------

const CONTRACT_ROUTE = "GET /api/v1/flows/{id}/run-contract/";
const START_ROUTE = "POST /api/v1/flows/{id}/runs/";

class FakeUpload {
  static sent: File[] = [];
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

/** The browser's recorder: `data` on every stop. */
class FakeMediaRecorder {
  static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
  static data = "audio";
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
  requestData() {}
  stop() {
    this.ondataavailable?.({ data: new Blob([FakeMediaRecorder.data], { type: "audio/webm" }) });
    this.state = "inactive";
    queueMicrotask(() => this.onstop?.(new Event("stop")));
  }
}

const microphone = vi.fn<() => Promise<MediaStream>>();

function installBrowser() {
  const track = Object.assign(new EventTarget(), { stop: vi.fn() });
  microphone.mockResolvedValue({
    getTracks: () => [track],
    getAudioTracks: () => [track]
  } as unknown as MediaStream);
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: microphone }
  });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("AudioContext", undefined);
  Object.defineProperty(navigator, "locks", { configurable: true, value: fakeLocks().locks });
}

const audioContract = (): RunContract =>
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
      live: { available: false, reason: "model_not_realtime" },
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

/** A part kept on the device from an earlier visit, by the signed-in person of `renderInApp`. */
function keptPart(
  sessionId: string,
  text: string,
  capturedAt: number,
  mimeType = "audio/webm"
): StoredPart {
  return {
    flowId: "flow-1",
    stepId: "step-1",
    sessionId,
    index: 0,
    blob: new Blob([text], { type: mimeType }),
    mimeType,
    durationMs: 30_000,
    capturedAt,
    interrupted: false,
    contract: {
      publishedFlowVersion: 4,
      inputFormat: "audio",
      maxFiles: 4,
      maxFileSizeBytes: null,
      acceptedMimetypes: ["audio/webm", "audio/mp4"]
    },
    streamed: false,
    userId: "user-1"
  };
}

function Harness() {
  const [open, setOpen] = useState(false);
  return createElement(
    "div",
    null,
    createElement("button", { type: "button", onClick: () => setOpen(true) }, "Kör"),
    createElement(StartRunDialog, {
      flow: makeFlow({ published_version: 4 }),
      open,
      onOpenChange: setOpen,
      onStarted: () => {}
    })
  );
}

async function openForm() {
  fireEvent.click(screen.getByRole("button", { name: "Kör" }));
  const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
  await within(dialog).findByText(/^Mötet/);
  return dialog;
}

async function renderForm() {
  api.routes[CONTRACT_ROUTE] = () => ({ body: audioContract() });
  api.routes[START_ROUTE] = () => ({ status: 201, body: { id: "run-1", status: "queued" } });
  renderInApp(createElement(Harness), { appContext: testAppContext({ user: { id: "user-1" } }) });
  return openForm();
}

const button = (dialog: HTMLElement, name: string) => within(dialog).getByRole("button", { name });
const SESSION_A = "0a1b2c3d-0000-4000-8000-00000000000a";
const SESSION_B = "0a1b2c3d-0000-4000-8000-00000000000b";
/** Two hours ago, on the minute. */
const RECENT = Math.floor(Date.now() / 60_000) * 60_000 - 2 * 60 * 60 * 1000;

describe("loss catalogue: the start form", () => {
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
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:${crypto.randomUUID()}`);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    api.routes = {};
    FakeUpload.sent = [];
    FakeMediaRecorder.data = "audio";
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

  // cut review A F5: a fix must keep Discard after a refused Continue on the recording the refusal was about, so another kept recording is never removed.
  it("base keeps: Discard after a refusal for format removes the refused recording, and the other kept recording's bytes stay", async () => {
    installBrowser();
    // Same length and minute: the offers look alike. A is a second newer and offered first.
    await device.db.putPart(keptPart(SESSION_B, "BBBB", RECENT));
    await device.db.putPart(keptPart(SESSION_A, "AAAA", RECENT + 1_000, "audio/ogg"));
    const dialog = await renderForm();

    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    expect(
      await within(dialog).findByText(messages.flow_transcript_resume_type_not_accepted)
    ).toBeTruthy();
    fireEvent.click(button(dialog, messages.flow_transcript_resume_discard));

    await waitFor(() => expect(device.db.parts.size).toBe(1));
    expect(await onDevice(device.db)).toEqual({ [SESSION_B]: ["0:BBBB"] });
    expect(FakeUpload.sent).toHaveLength(0);
    // B is offered next.
    expect(await within(dialog).findByText(messages.flow_transcript_resume_title)).toBeTruthy();
  });

  // final review F18: a fix must let the form reach an older kept recording behind a newer one, so continuing it gives it new activity before the expiry cleanup.
  it("base keeps: a second Continue reaches the older recording, recording again goes on with it, and the expiry cleanup keeps it", async () => {
    installBrowser();
    // The newer recording (another tab's); the older one five minutes before its day runs out.
    const olderAt = Date.now() - RECORDING_TTL_MS + 5 * 60_000 - 30_000;
    await device.db.putPart(keptPart(SESSION_A, "NEWER", RECENT));
    await device.db.putPart(keptPart(SESSION_B, "ONLY-OLDER", olderAt));
    FakeMediaRecorder.data = "EXTENSION";
    const dialog = await renderForm();

    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    fireEvent.click(
      await within(dialog).findByRole("button", { name: messages.flow_transcript_resume_continue })
    );
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(2));
    // The newer, then the older, went onto the form.
    expect(FakeUpload.sent.map((file) => file.name.slice(10, 46))).toEqual([SESSION_A, SESSION_B]);
    expect(await bytes(FakeUpload.sent[1]!)).toBe("ONLY-OLDER");

    fireEvent.click(button(dialog, messages.flow_transcript_rec_continue));
    await within(dialog).findByRole("button", { name: messages.flow_transcript_rec_stop });
    fireEvent.click(button(dialog, messages.flow_transcript_rec_stop));
    await waitFor(() => expect(device.db.parts.size).toBe(3));

    // Another tab scans once the older recording's own day has run out.
    const later = new RecordingKeeper(
      "flow-1",
      "user-1",
      device.db,
      null,
      () => Date.now() + 10 * 60_000
    );
    await later.scan("step-1");
    expect(await onDevice(device.db)).toEqual({
      [SESSION_A]: ["0:NEWER"],
      [SESSION_B]: ["0:ONLY-OLDER", "1:EXTENSION"]
    });
  });

  // final review F19 (derived, not the reviewer's reproduction): a fix must not let a recording whose device copy the expiry cleanup took during Continue close as saved for later.
  it("base loses: after Continue raced another tab's expiry cleanup, Save for later closes the form with nothing on the device", async () => {
    installBrowser();
    const soloAt = Date.now() - RECORDING_TTL_MS + 5 * 60_000 - 30_000;
    await device.db.putPart(keptPart(SESSION_A, "ONLY-SOLO", soloAt));
    const dialog = await renderForm();
    const continueButton = await within(dialog).findByRole("button", {
      name: messages.flow_transcript_resume_continue
    });

    // Another tab's scan, past the day, is about to delete the recording.
    const deleteSession = device.db.deleteSession.bind(device.db);
    const held = gate();
    const deleting = vi
      .spyOn(device.db, "deleteSession")
      .mockImplementationOnce(async (...args) => {
        await held.opened;
        return deleteSession(...args);
      });
    const other = new RecordingKeeper(
      "flow-1",
      "user-1",
      device.db,
      null,
      () => Date.now() + 10 * 60_000
    );
    const scanning = other.scan("step-1");
    await vi.waitFor(() => expect(deleting).toHaveBeenCalled());

    fireEvent.click(continueButton);
    await waitFor(() => expect(FakeUpload.sent).toHaveLength(1));
    held.open();
    await scanning;
    expect(await bytes(FakeUpload.sent[0]!)).toBe("ONLY-SOLO");
    expect(await onDevice(device.db)).toEqual({});

    fireEvent.click(button(dialog, messages.flow_transcript_save_later));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const again = await openForm();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(within(again).queryByText(messages.flow_transcript_resume_title)).toBeNull();
    expect(device.db.parts.size).toBe(0);
  });
});
