import { readFileSync } from "node:fs";
import path from "node:path";
import { runInNewContext } from "node:vm";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FINAL_TEXT_WAIT_MS, LiveTranscript, RECONNECT_DELAYS_MS } from "./live-transcript";
import { FakeNode, FakeSocket, TICKET, fakeGraph, installLiveFakes } from "./testing/live-fakes";

function makeLive(openSession = vi.fn(() => Promise.resolve(TICKET))) {
  const live = new LiveTranscript({
    openSession,
    socketUrl: (path) => `wss://app.example${path}`,
    createSocket: (url, protocols) => new FakeSocket(url, protocols) as unknown as WebSocket,
    createNode: () => new FakeNode() as unknown as AudioWorkletNode,
    newRecordingId: () => "recording-0001"
  });
  return { live, openSession };
}

/** Starts a session and lets the socket open and say ready. */
async function listening(live: LiveTranscript, { keepsTranscript = true } = {}) {
  await live.start(fakeGraph());
  await vi.waitFor(() => expect(FakeSocket.instances.length).toBeGreaterThan(0));
  const socket = FakeSocket.instances.at(-1)!;
  socket.open();
  socket.receive({
    type: "ready",
    sample_rate: 16000,
    max_seconds: 18000,
    keeps_transcript: keepsTranscript
  });
  return { socket, node: FakeNode.instances.at(-1)! };
}

const text = (live: LiveTranscript) =>
  live
    .getSnapshot()
    .pieces.map((piece) => piece.text)
    .join("");

beforeEach(installLiveFakes);
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LiveTranscript", () => {
  it("names the recording, offers the ticket and sends the audio heard before the socket opened", async () => {
    const { live, openSession } = makeLive();
    await live.start(fakeGraph());
    const node = FakeNode.instances[0]!;
    node.frame(1);
    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0]!;
    expect(openSession).toHaveBeenCalledWith("recording-0001");
    expect(socket.url).toBe("wss://app.example/api/v1/live-transcription");
    expect(socket.protocols).toEqual(["eneo-live.v1", "ticket.t0k3n"]);

    socket.open();
    node.frame(2);
    expect(socket.frameTags).toEqual([1, 2]);
    socket.receive({ type: "ready" });
    expect(live.getSnapshot().status).toBe("listening");
  });

  it("appends the text and keeps a stored transcript of a recording heard whole", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    node.frame(1);
    socket.receive({ type: "transcript.delta", text: "Hej " });
    socket.receive({ type: "transcript.delta", text: "allihop" });
    live.stop();
    expect(live.getSnapshot()).toMatchObject({ status: "finished", finishing: true });
    await vi.waitFor(() =>
      expect(socket.texts).toEqual([{ type: "stop", produced_samples: 1600 }])
    );

    const settled = live.settled();
    socket.receive({ type: "transcript.done", text: "Hej allihop.", transcript_id: "tr-1" });
    await settled;
    expect(text(live)).toBe("Hej allihop.");
    expect(live.transcriptId).toBe("tr-1");
    expect(live.getSnapshot().finishing).toBe(false);
  });

  it("does not hold the run for a preview the core will not keep", async () => {
    // A session the core keeps no text for, such as one without a recording id.
    const { live } = makeLive();
    const { socket, node } = await listening(live, { keepsTranscript: false });
    node.frame(1);
    socket.receive({ type: "transcript.delta", text: "Hej" });
    live.stop();
    expect(live.getSnapshot()).toMatchObject({ status: "finished", finishing: false });
    await live.settled();
    await vi.waitFor(() => expect(socket.texts).toEqual([{ type: "stop" }]));
    socket.receive({ type: "transcript.done", text: "Hej.", transcript_id: "tr-1" });
    expect(text(live)).toBe("Hej.");
    expect(live.transcriptId).toBeNull();
  });

  it("stops waiting for the final text after its bound", async () => {
    const { live } = makeLive();
    await listening(live);
    vi.useFakeTimers();
    live.stop();
    const settled = live.settled();
    await vi.advanceTimersByTimeAsync(FINAL_TEXT_WAIT_MS);
    await settled;
    expect(live.getSnapshot().finishing).toBe(false);
  });

  it("keeps a paused recording whole: the worklet holds the pause, the page drops nothing", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    node.frame(1);
    live.pause(true);
    expect(node.port.postMessage).toHaveBeenLastCalledWith("pause");
    // The frame the worklet sent as it heard of the pause was heard before it.
    node.frame(2, 640);
    live.pause(false);
    expect(node.port.postMessage).toHaveBeenLastCalledWith("resume");
    node.frame(3);
    expect(socket.frameTags).toEqual([1, 2, 3]);

    live.stop();
    expect(live.getSnapshot().finishing).toBe(true);
    await vi.waitFor(() =>
      expect(socket.texts).toEqual([{ type: "stop", produced_samples: 3520 }])
    );
    socket.receive({ type: "transcript.done", text: "", transcript_id: "tr-1" });
    expect(live.transcriptId).toBe("tr-1");
  });

  it("counts a recording stopped while paused", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    node.frame(1);
    live.pause(true);
    live.stop();
    expect(live.getSnapshot().finishing).toBe(true);
    await vi.waitFor(() =>
      expect(socket.texts).toEqual([{ type: "stop", produced_samples: 1600 }])
    );
  });

  it("names where each part after the first began, and waits for the final text", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    node.frame(1);
    live.markPart();
    expect(node.port.postMessage).toHaveBeenLastCalledWith("mark");
    node.frame(2);
    live.markPart();
    node.frame(3);
    for (const key of ["a", "b", "c"]) live.addPart(key);
    live.stop();
    expect(live.getSnapshot().finishing).toBe(true);
    await vi.waitFor(() =>
      expect(socket.texts).toEqual([
        { type: "stop", produced_samples: 4800, part_start_samples: [1600, 3200] }
      ])
    );

    const settled = live.settled();
    socket.receive({ type: "transcript.done", text: "", transcript_id: "tr-1" });
    await settled;
    expect(live.transcriptFor(["a", "b", "c"])).toBe("tr-1");
    expect(live.transcriptFor(["b", "a", "c"])).toBeUndefined();
    expect(live.transcriptFor(["a", "b"])).toBeUndefined();
    expect(live.transcriptFor(["a", "b", "c", "d"])).toBeUndefined();
  });

  it("leaves out a part start the core would refuse, and the transcript then fits one part fewer", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    node.frame(1);
    live.markPart();
    // No audio came between these two, nor after the last: neither starts a part.
    live.markPart();
    node.frame(2);
    live.markPart();
    live.stop();
    await vi.waitFor(() =>
      expect(socket.texts).toEqual([
        { type: "stop", produced_samples: 3200, part_start_samples: [1600] }
      ])
    );
    socket.receive({ type: "transcript.done", text: "", transcript_id: "tr-1" });
    for (const key of ["a", "b", "c", "d"]) live.addPart(key);
    expect(live.transcriptFor(["a", "b", "c", "d"])).toBeUndefined();
  });

  it("offers the transcript of one part only for that part", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    node.frame(1);
    live.addPart("a");
    live.stop();
    await vi.waitFor(() => expect(socket.texts).toHaveLength(1));
    socket.receive({ type: "transcript.done", text: "", transcript_id: "tr-1" });
    expect(live.transcriptFor(["a"])).toBe("tr-1");
    expect(live.transcriptFor(["b"])).toBeUndefined();
    expect(live.transcriptFor(["x", "a"])).toBeUndefined();
  });

  it("connects again after a drop while the recording goes on, and the text goes on", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { live, openSession } = makeLive();
    const { socket } = await listening(live);
    socket.receive({ type: "transcript.delta", text: "Första" });
    socket.drop();
    expect(live.getSnapshot().status).toBe("reconnecting");

    await vi.advanceTimersByTimeAsync(RECONNECT_DELAYS_MS[0]);
    expect(openSession).toHaveBeenLastCalledWith(undefined);
    const again = FakeSocket.instances.at(-1)!;
    expect(again).not.toBe(socket);
    again.open();
    again.receive({ type: "ready" });
    again.receive({ type: "transcript.delta", text: "andra" });
    expect(live.getSnapshot().status).toBe("listening");
    expect(text(live)).toBe("Första andra");

    // A reconnected session never stands in for the recording.
    live.stop();
    expect(live.getSnapshot().finishing).toBe(false);
  });

  it("gives up after the last reconnection and keeps the text", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const openSession = vi.fn(() => Promise.resolve(TICKET));
    const { live } = makeLive(openSession);
    const { socket } = await listening(live);
    socket.receive({ type: "transcript.delta", text: "Kvar" });
    socket.drop();
    for (const delay of RECONNECT_DELAYS_MS) {
      await vi.advanceTimersByTimeAsync(delay);
      FakeSocket.instances.at(-1)!.drop();
    }
    expect(live.getSnapshot()).toMatchObject({ status: "interrupted" });
    expect(text(live)).toBe("Kvar");
  });

  it("is unavailable when the session route refuses, and the recording is not told to wait", async () => {
    const { live } = makeLive(vi.fn(() => Promise.reject(new Error("409"))));
    await live.start(fakeGraph());
    await vi.waitFor(() => expect(live.getSnapshot().status).toBe("unavailable"));
    expect(live.getSnapshot().errorCode).toBe("unavailable");
  });

  it("shows nothing of a discarded recording, not even a late message", async () => {
    const { live } = makeLive();
    const { socket } = await listening(live);
    live.discard();
    socket.receive({ type: "transcript.delta", text: "sent" });
    expect(live.getSnapshot()).toMatchObject({ status: "idle", pieces: [] });
  });
});

/** The worklet module as the audio thread runs it at `rate` Hz, and what it posts to the page. */
function loadWorklet(rate: number) {
  type Processor = {
    port: { onmessage: (event: { data: unknown }) => void };
    process: (inputs: Float32Array[][]) => boolean;
  };
  let Registered: (new () => Processor) | undefined;
  const posted: unknown[] = [];
  class AudioWorkletProcessor {
    port = { onmessage: null, postMessage: (data: unknown) => posted.push(data) };
  }
  const file = path.resolve(import.meta.dirname, "../../../../../public/flows/pcm16-worklet.js");
  runInNewContext(readFileSync(file, "utf8"), {
    registerProcessor: (_name: string, processor: new () => Processor) => {
      Registered = processor;
    },
    AudioWorkletProcessor,
    sampleRate: rate
  });
  const processor = new Registered!();
  return {
    posted,
    send: (data: string) => processor.port.onmessage({ data }),
    /** One render quantum of `samples` input samples. */
    hear: (samples: number) => processor.process([[new Float32Array(samples).fill(0.5)]]),
    // The worklet's frames are ArrayBuffers of its own realm.
    frames: () =>
      posted.flatMap((item) =>
        typeof item === "object" ? [(item as ArrayBuffer).byteLength / 2] : []
      ),
    answers: () => posted.filter((item) => typeof item !== "object")
  };
}

describe("The PCM16 worklet", () => {
  it("answers a mark with the samples written so far, the frame in progress included", () => {
    const worklet = loadWorklet(48_000);
    worklet.hear(128);
    worklet.hear(128);
    worklet.send("mark");
    // 256 samples at 48 kHz are 85 whole samples at 16 kHz, none posted yet.
    expect(worklet.posted).toEqual([85]);
  });

  it("sends the frame in progress at a pause, hears nothing until the resume, and counts on", () => {
    const worklet = loadWorklet(16_000);
    worklet.hear(128);
    worklet.send("pause");
    worklet.hear(128);
    worklet.send("mark");
    worklet.send("resume");
    worklet.hear(128);
    worklet.send("flush");
    expect(worklet.frames()).toEqual([128, 128]);
    expect(worklet.answers()).toEqual([128, "flushed"]);
  });
});
