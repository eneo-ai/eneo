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
async function listening(live: LiveTranscript) {
  await live.start(fakeGraph());
  await vi.waitFor(() => expect(FakeSocket.instances.length).toBeGreaterThan(0));
  const socket = FakeSocket.instances.at(-1)!;
  socket.open();
  socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
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

  it("keeps a paused recording's text a draft: no count, no stored transcript", async () => {
    const { live } = makeLive();
    const { socket, node } = await listening(live);
    live.pause(true);
    node.frame(9);
    live.pause(false);
    expect(socket.frameTags).toEqual([]);
    live.stop();
    expect(live.getSnapshot().finishing).toBe(false);
    await vi.waitFor(() => expect(socket.texts).toEqual([{ type: "stop" }]));
    socket.receive({ type: "transcript.done", text: "", transcript_id: "tr-1" });
    expect(live.transcriptId).toBeNull();
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
