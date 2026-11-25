// @vitest-environment jsdom
/**
 * What today's keeper, journal and store do in the flows a review of a cut
 * ("one form holds a kept recording") reproduced: the part number floor and
 * expiry just before "Continue", a Discard retried after it failed, and a
 * discard on the form. Each test states the base's outcome in exact bytes and
 * keys: "base loses" is a loss a fix must remove, "base keeps" is what no fix
 * may make worse.
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createElement, Fragment, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initializeBrowserSession, SESSION_GENERATION_HEADER } from "@/lib/api/refusal";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow } from "../../../flow-fixtures";
import { makeContract, makeInput } from "../../run-fixtures";
import type { RunContract } from "../../runs-api";
import { RecordingKeeper, resumeRefusal, type JournalPart } from "../recording-keeper";
import {
  memoryRecordings,
  partKey,
  RECORDING_TTL_MS,
  type ContractSnapshot,
  type StoredPart
} from "../recording-store";
import { FakeNode, FakeSocket } from "../testing/live-fakes";
import { fakeLocks } from "./catalog-locks";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../../../editor/testing/fixtures").apiStub>
}));

// The device's store, as the form finds it.
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

const CONTRACT: ContractSnapshot = {
  publishedFlowVersion: 4,
  inputFormat: "audio",
  maxFiles: 4,
  maxFileSizeBytes: 10_000_000,
  acceptedMimetypes: ["audio/webm"]
};

const START = Date.UTC(2026, 9, 22, 8, 0, 0);

type Db = ReturnType<typeof memoryRecordings>;

/** One browser: one store and one lock manager, shared by every tab's keeper. */
function browser() {
  const db = memoryRecordings();
  const lockManager = fakeLocks();
  let now = START;
  return {
    db,
    lockManager,
    /** A form of the signed-in person in a tab of this browser. */
    tab: () => new RecordingKeeper("flow-1", "user-a", db, lockManager.locks, () => now),
    later: (ms: number) => {
      now += ms;
    }
  };
}

const part = (index: number, sessionId = "rec-1"): JournalPart => ({
  sessionId,
  index,
  mimeType: "audio/webm;codecs=opus",
  capturedAt: START + index * 60_000
});

const finished = (index: number, audio: string, sessionId = "rec-1") => ({
  sessionId,
  index,
  blob: new Blob([audio], { type: "audio/webm" }),
  mimeType: "audio/webm",
  durationMs: 1_000,
  capturedAt: START + index * 60_000,
  contract: CONTRACT,
  streamed: false
});

const key = (index: number, sessionId = "rec-1") =>
  partKey({ flowId: "flow-1", stepId: "step-1", sessionId, index });

/** Every key on the device. */
const keys = (db: Db) => ({
  parts: [...db.parts.keys()],
  journals: [...db.journals.keys()],
  chunks: [...db.chunks.keys()]
});

/** A blob's text: jsdom's Blob has no `text()`, its FileReader reads it. */
const text = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });

const bytes = (parts: readonly StoredPart[]) => Promise.all(parts.map((p) => text(p.blob)));

/** Lets the journal's queued writes land. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("the cut's review flows, as the base keeps a recording", () => {
  // cut review B F3: a fix must keep the full part, unrebuilt, when another tab scans mid-write.
  it("base keeps: a finished part still being written when another tab scans keeps its full audio", async () => {
    const { db, tab } = browser();
    const tabA = tab();
    const journal = tabA.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journal.begin(part(0));
    journal.append(part(0), new Blob(["AA"], { type: "audio/webm" }), 500);
    await settle();
    let write = () => {};
    const written = new Promise<void>((resolve) => {
      write = resolve;
    });
    const putPart = db.putPart.bind(db);
    const put = vi.spyOn(db, "putPart").mockImplementation(async (stored) => {
      if (!stored.interrupted) await written;
      return putPart(stored);
    });
    const kept = tabA.keepPart("step-1", finished(0, "AAAA-full"));
    await settle();
    // The base has no hold to let go: the part's journal lock stays with tab A until it commits.
    const scanned = tab().scan("step-1");
    await settle();
    write();
    expect(await kept).toBe("device");
    await scanned;
    await tab().scan("step-1");

    expect(put.mock.calls.some(([stored]) => stored.interrupted)).toBe(false);
    expect(await bytes(await tab().readSession("step-1", "rec-1"))).toEqual(["AAAA-full"]);
    expect(keys(db)).toEqual({ parts: [key(0)], journals: [], chunks: [] });
  });

  // cut review B F15: a fix must give Continue just before expiry the full bytes despite a clean-up.
  it("base keeps: Continue just before a recording's day runs out reads its full bytes before another tab's clean-up", async () => {
    const { tab, later } = browser();
    await tab().keepPart("step-1", finished(0, "AAAA"));
    // One millisecond before the day since its last activity runs out.
    later(1_000 + RECORDING_TTL_MS - 1);
    const continuing = tab();
    expect((await continuing.scan("step-1")).saved).toHaveLength(1);

    const read = continuing.readSession("step-1", "rec-1");
    later(2);
    const parts = await read;
    await tab().scan("step-1");

    expect(parts.map((p) => p.index)).toEqual([0]);
    expect(await bytes(parts)).toEqual(["AAAA"]);
    // Nothing the step refuses: the form adds the part as a row and uploads it.
    expect(resumeRefusal(CONTRACT, parts)).toBeNull();
  });

  // cut review B F15: a fix must not count a continued recording as kept once clean-up removed it.
  it("base loses: another tab's clean-up removes a just-continued recording from the device while the form counts it as kept there", async () => {
    const { db, tab, later } = browser();
    await tab().keepPart("step-1", finished(0, "AAAA"));
    later(1_000 + RECORDING_TTL_MS - 1);
    const continuing = tab();
    const parts = await continuing.readSession("step-1", "rec-1");
    continuing.adopt("step-1", parts);
    later(2);
    await tab().scan("step-1");

    expect(keys(db)).toEqual({ parts: [], journals: [], chunks: [] });
    // "Save and continue later" and the upload backlog trust this: the only copy is the tab's.
    expect(continuing.keeping("step-1", "rec-1", 0)).toBe("device");
  });

  // cut review B F16: a fix must keep the gone tab's unfinished audio and leave it continuable.
  it("base loses: Continue in a second tab after the recording tab went writes its next part over that tab's unfinished part", async () => {
    const { db, tab } = browser();
    const tabA = tab();
    await tabA.keepPart("step-1", finished(0, "P0"));
    await tabA.keepPart("step-1", finished(1, "P1"));
    const journalA = tabA.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journalA.begin(part(2));
    journalA.append(part(2), new Blob(["AAAA"], { type: "audio/webm" }), 1_000);
    journalA.append(part(2), new Blob(["aaaa"], { type: "audio/webm" }), 2_000);
    await settle();

    // Tab B opens the form while tab A records part 2: its scan skips the locked journal.
    const tabB = tab();
    expect((await tabB.scan("step-1")).saved.map((saved) => saved.parts)).toEqual([2]);
    // Tab A goes: its lock is let go, its journal stays (no scan runs in between).
    journalA.leave(part(2));
    await settle();
    expect(keys(db).journals).toEqual([key(2)]);
    expect(keys(db).chunks).toEqual([`${key(2)}::000000`, `${key(2)}::000001`]);

    // Tab B continues: the form numbers its next part after its own rows, 0 and 1, so 2.
    const continued = await tabB.readSession("step-1", "rec-1");
    expect(continued.map((p) => p.index)).toEqual([0, 1]);
    tabB.adopt("step-1", continued);
    const journalB = tabB.journalFor(
      "step-1",
      () => CONTRACT,
      () => false
    );
    journalB.begin(part(2));
    journalB.append(part(2), new Blob(["BBBB"], { type: "audio/webm" }), 1_000);
    await settle();
    expect(await tabB.keepPart("step-1", finished(2, "BBBB"))).toBe("device");

    // Reopened: three parts, tab A's unfinished audio gone, chunk 1 included, which B never wrote.
    const reopened = tab();
    expect((await reopened.scan("step-1")).saved.map((saved) => saved.parts)).toEqual([3]);
    const parts = await reopened.readSession("step-1", "rec-1");
    expect(await bytes(parts)).toEqual(["P0", "P1", "BBBB"]);
    expect(keys(db)).toEqual({ parts: [key(0), key(1), key(2)], journals: [], chunks: [] });
    // A step that takes three files still takes it: the recording can be continued.
    expect(resumeRefusal({ ...CONTRACT, maxFiles: 3 }, parts)).toBeNull();
  });

  // cut review B F17: a fix must discard only the form's recording; a stale offer adds nothing.
  it("base keeps: a discard on the form removes only its recording, and another tab's stale offer of it adds nothing", async () => {
    const { db, tab } = browser();
    const form = tab();
    await form.keepPart("step-1", finished(0, "MINE", "rec-1"));
    await tab().keepPart("step-1", finished(0, "OTHER", "rec-2"));
    const other = tab();
    expect((await other.scan("step-1")).saved.map((saved) => saved.sessionId).sort()).toEqual([
      "rec-1",
      "rec-2"
    ]);

    // The form's "Kassera" on its own recording.
    expect(await form.forgetSession("step-1", "rec-1")).toBe(true);

    // The other tab's offer of it: Continue finds no part and adds no row.
    expect(await other.readSession("step-1", "rec-1")).toEqual([]);
    expect(await bytes(await other.readSession("step-1", "rec-2"))).toEqual(["OTHER"]);
    expect(keys(db)).toEqual({ parts: [key(0, "rec-2")], journals: [], chunks: [] });
  });
});

// The form, as run-recorder.test.tsx renders it: only what the resume prompt needs.
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
  stop() {
    this.state = "inactive";
  }
}

const RUN_CONTRACT = "GET /api/v1/flows/{id}/run-contract/";
const RUN_START = "POST /api/v1/flows/{id}/runs/";

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

/** Two hours ago, inside the keeper's day. */
const KEPT_BASE = Math.floor(Date.now() / 60_000) * 60_000 - 2 * 60 * 60 * 1000;

function keptPart(sessionId: string, index: number, startedAt: number): StoredPart {
  return {
    flowId: "flow-1",
    stepId: "step-1",
    sessionId,
    index,
    blob: new Blob([`${sessionId} part ${index}`], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 30_000,
    capturedAt: startedAt + index * 60_000,
    interrupted: false,
    contract: CONTRACT,
    streamed: false,
    // The signed-in person in `renderInApp`.
    userId: "user-1"
  };
}

function Harness() {
  const [open, setOpen] = useState(false);
  return createElement(
    Fragment,
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

describe("the cut's review flows, through the form", () => {
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
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn() }
    });
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("AudioWorkletNode", FakeNode);
    vi.stubGlobal("WebSocket", FakeSocket);
    Object.defineProperty(navigator, "locks", { configurable: true, value: fakeLocks().locks });
    api.routes = {};
    device.db = memoryRecordings();
  });

  afterEach(() => {
    cleanup();
    api.stub.calls.length = 0;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // cut review B F5: a fix must retry a failed Discard on the same recording, never another one.
  it("base keeps: Discard pressed again after it failed removes the same recording, and the other kept recording stays", async () => {
    const older = "0a1b2c3d-0000-4000-8000-00000000000b";
    const newer = "0a1b2c3d-0000-4000-8000-00000000000a";
    await device.db.putPart(keptPart(older, 0, KEPT_BASE - 30 * 60_000));
    await device.db.putPart(keptPart(newer, 0, KEPT_BASE));
    await device.db.putPart(keptPart(newer, 1, KEPT_BASE));
    const removed = vi
      .spyOn(device.db, "deleteSession")
      .mockRejectedValueOnce(new Error("blocked"));

    api.routes[RUN_CONTRACT] = () => ({ body: audioContract() });
    api.routes[RUN_START] = () => ({ status: 201, body: { id: "run-1", status: "queued" } });
    renderInApp(createElement(Harness), { appContext: testAppContext({ user: { id: "user-1" } }) });
    fireEvent.click(screen.getByRole("button", { name: "Kör" }));
    const dialog = await screen.findByRole("dialog", { name: "Kör Medborgarbrev" });
    // The newer recording, of two parts, is offered first.
    expect(await within(dialog).findByText(/består av 2 delar/)).toBeTruthy();

    const discard = () =>
      fireEvent.click(
        within(dialog).getByRole("button", { name: messages.flow_transcript_resume_discard })
      );
    discard();
    expect(
      await within(dialog).findByText(messages.flow_transcript_resume_discard_failed)
    ).toBeTruthy();
    // Still the same offer after the failure.
    expect(within(dialog).getByText(/består av 2 delar/)).toBeTruthy();
    discard();

    await waitFor(() =>
      expect([...device.db.parts.keys()]).toEqual([
        partKey({ flowId: "flow-1", stepId: "step-1", sessionId: older, index: 0 })
      ])
    );
    expect(removed.mock.calls.map(([, , sessionId]) => sessionId)).toEqual([newer, newer]);
    expect(await text([...device.db.parts.values()][0]!.blob)).toBe(`${older} part 0`);
    // The other recording is offered next.
    expect(await within(dialog).findByText(/består av en del/)).toBeTruthy();
  });
});
