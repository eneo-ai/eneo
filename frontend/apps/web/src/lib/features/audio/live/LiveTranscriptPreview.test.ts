import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EneoError, type Eneo, type FlowLiveTranscriptionSession } from "@eneo/eneo-js";
import {
  FLUSH_TIMEOUT_MS,
  LiveTranscriptPreview,
  MAX_QUEUED_FRAMES,
  type RecorderAudioGraph
} from "./LiveTranscriptPreview.svelte";
import {
  FakeLiveSocket,
  FakeWorkletNode,
  frameTags,
  installLiveTranscriptFakes,
  liveSession
} from "./liveTranscriptTestFakes";
import { PCM16_FLUSH, PCM16_FLUSHED } from "./pcm16-worklet.js";

beforeEach(() => {
  installLiveTranscriptFakes();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function setup({
  createSession = vi.fn(async () => liveSession),
  addModule = vi.fn(async () => undefined)
}: {
  createSession?: () => Promise<FlowLiveTranscriptionSession>;
  addModule?: () => Promise<void>;
} = {}) {
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const graph = {
    context: { audioWorklet: { addModule } },
    source
  } as unknown as RecorderAudioGraph;
  const eneo = {
    flows: { liveTranscription: { createSession } },
    client: { baseUrl: new URL("https://eneo.example.test") }
  } as unknown as Eneo;
  const preview = new LiveTranscriptPreview();
  const onListening = vi.fn();
  const start = (signal?: AbortSignal) =>
    preview.start(graph, { eneo, flowId: "flow-1", stepId: "step-audio", onListening, signal });
  return { preview, start, createSession, addModule, source, onListening };
}

// A request the test answers, so audio can arrive before it does.
function pending<T>() {
  let settle: (value: T) => void = () => {};
  let fail: (error: unknown) => void = () => {};
  const request = vi.fn(
    () =>
      new Promise<T>((resolve, reject) => {
        settle = resolve;
        fail = reject;
      })
  );
  return { request, settle: (value: T) => settle(value), fail: (error: unknown) => fail(error) };
}

async function tapped(count = 1) {
  await vi.waitFor(() => expect(FakeWorkletNode.instances).toHaveLength(count));
  return FakeWorkletNode.instances[count - 1];
}

async function connected(count = 1) {
  await vi.waitFor(() => expect(FakeLiveSocket.instances).toHaveLength(count));
  return FakeLiveSocket.instances[count - 1];
}

function texts(preview: LiveTranscriptPreview) {
  return preview.pieces.map((piece) => piece.text);
}

async function listening(harness: ReturnType<typeof setup>, count = 1) {
  await harness.start();
  const socket = await connected(count);
  socket.open();
  socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
  return { socket, node: FakeWorkletNode.instances[count - 1] };
}

describe("LiveTranscriptPreview", () => {
  it("lets the recorder start once the audio is tapped, while the ticket is still out", async () => {
    const ticket = pending<FlowLiveTranscriptionSession>();
    const harness = setup({ createSession: ticket.request });

    await harness.start();

    expect(harness.source.connect).toHaveBeenCalledWith(FakeWorkletNode.instances[0]);
    expect(FakeLiveSocket.instances).toHaveLength(0);
  });

  it("keeps the recording's first words: audio waits in order until the socket opens", async () => {
    const ticket = pending<FlowLiveTranscriptionSession>();
    const harness = setup({ createSession: ticket.request });
    void harness.start();

    const node = await tapped();
    node.frame(1);
    ticket.settle(liveSession);
    const socket = await connected();
    node.frame(2);
    expect(socket.frames).toHaveLength(0);

    socket.open();
    node.frame(3);
    expect(frameTags(socket)).toEqual([1, 2, 3]);
  });

  it("is unavailable, and never taps late, when the recorder stops waiting for the tap", async () => {
    const module = pending<void>();
    const harness = setup({ addModule: module.request });
    const waiting = new AbortController();
    void harness.start(waiting.signal);

    waiting.abort();
    expect(harness.preview.status).toBe("unavailable");
    expect(harness.preview.errorCode).toBe("audio_timeout");

    module.settle();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(FakeWorkletNode.instances).toHaveLength(0);
    expect(harness.source.connect).not.toHaveBeenCalled();
    expect(FakeLiveSocket.instances).toHaveLength(0);
  });

  it("streams the recorder's audio and shows the committed text until the final text", async () => {
    const harness = setup();
    const started = harness.start();
    expect(harness.preview.status).toBe("connecting");
    await started;

    const socket = await connected();
    expect(harness.createSession).toHaveBeenCalledWith({ id: "flow-1", stepId: "step-audio" });
    expect(socket.url).toBe("wss://eneo.example.test/api/v1/flows/live-transcription");
    expect(socket.protocols).toEqual(["eneo-live.v1", "ticket.t0k3n"]);

    socket.open();
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    expect(harness.preview.status).toBe("listening");
    expect(harness.onListening).toHaveBeenCalledOnce();

    const node = FakeWorkletNode.instances[0];
    node.frame();
    socket.receive({ type: "transcript.delta", text: "Hej" });
    socket.receive({ type: "transcript.delta", text: " och välkomna" });
    expect(socket.frames).toHaveLength(1);
    expect(texts(harness.preview)).toEqual(["Hej", " och välkomna"]);

    harness.preview.stop();
    harness.preview.stop();
    expect(harness.preview.status).toBe("finished");
    await vi.waitFor(() => expect(socket.texts).toEqual([JSON.stringify({ type: "stop" })]));
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    expect(socket.close).not.toHaveBeenCalled();

    socket.receive({ type: "transcript.done", text: "Hej och välkomna." });
    expect(texts(harness.preview).join("")).toBe("Hej och välkomna.");
    expect(socket.close).toHaveBeenCalledOnce();
    expect(harness.preview.status).toBe("finished");
  });

  it("sends the rest of the last frame before it asks for the final text", async () => {
    const harness = setup();
    const { socket, node } = await listening(harness);
    node.answersFlush = false;

    harness.preview.stop();
    expect(node.port.postMessage).toHaveBeenCalledWith(PCM16_FLUSH);
    expect(socket.texts).toEqual([]);

    node.frame(9, 1600);
    node.post(PCM16_FLUSHED);
    expect(frameTags(socket)).toEqual([9]);
    expect(socket.sent.at(-1)).toBe(JSON.stringify({ type: "stop" }));
  });

  it("asks for the final text anyway when the worklet cannot answer", async () => {
    const harness = setup();
    const { socket, node } = await listening(harness);
    node.answersFlush = false;
    vi.useFakeTimers();

    harness.preview.stop();
    vi.advanceTimersByTime(FLUSH_TIMEOUT_MS - 1);
    expect(socket.texts).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(socket.texts).toEqual([JSON.stringify({ type: "stop" })]);
  });

  it("ends as interrupted with the code of an error event, and as finished with the recording", async () => {
    const harness = setup();
    const { socket, node } = await listening(harness);

    socket.receive({
      type: "error",
      code: "upstream_closed",
      message: "The transcription server closed the session.",
      retryable: true
    });
    node.frame();

    expect(harness.preview.status).toBe("interrupted");
    expect(harness.preview.errorCode).toBe("upstream_closed");
    expect(socket.frames).toHaveLength(0);
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);

    harness.preview.stop();
    expect(harness.preview.status).toBe("finished");
  });

  it("ends as interrupted when the socket drops", async () => {
    const harness = setup();
    const { socket } = await listening(harness);

    socket.drop();

    expect(harness.preview.status).toBe("interrupted");
  });

  it("ends the preview instead of dropping audio when the socket falls behind", async () => {
    const harness = setup();
    const { socket, node } = await listening(harness);
    node.frame();

    socket.bufferedAmount = 1024 * 1024;
    node.frame();
    node.frame();

    expect(socket.frames).toHaveLength(1);
    expect(harness.preview.status).toBe("interrupted");
    expect(harness.preview.errorCode).toBe("backpressure");
    expect(socket.close).toHaveBeenCalled();
  });

  it("is unavailable when the ticket is refused, and lets go of the recorder's audio", async () => {
    const ticket = pending<FlowLiveTranscriptionSession>();
    const harness = setup({ createSession: ticket.request });
    void harness.start();
    const node = await tapped();
    node.frame();

    ticket.fail(
      new EneoError("Live transcription is not available for this flow.", "RESPONSE", 409, 9057, {
        code: "flow_live_transcription_unavailable",
        context: { reason: "model_not_realtime" },
        eneo_error_code: 9057,
        message: "Live transcription is not available for this flow."
      })
    );

    await vi.waitFor(() => expect(harness.preview.status).toBe("unavailable"));
    expect(harness.preview.errorCode).toBe("model_not_realtime");
    expect(FakeLiveSocket.instances).toHaveLength(0);
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    expect(node.port.close).toHaveBeenCalled();
  });

  it("is unavailable, visibly, when the socket has not opened within the waiting audio's bound", async () => {
    const harness = setup();
    await harness.start();
    const socket = await connected();
    const node = FakeWorkletNode.instances[0];

    for (let index = 0; index < MAX_QUEUED_FRAMES; index += 1) node.frame();
    expect(harness.preview.status).toBe("connecting");
    node.frame();

    expect(harness.preview.status).toBe("unavailable");
    expect(harness.preview.errorCode).toBe("connect_timeout");
    expect(socket.close).toHaveBeenCalled();
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    socket.open();
    expect(socket.frames).toHaveLength(0);
  });

  it("lets go of everything when the recording stops while audio waits for the socket", async () => {
    const ticket = pending<FlowLiveTranscriptionSession>();
    const harness = setup({ createSession: ticket.request });
    void harness.start();
    const node = await tapped();
    node.frame();

    harness.preview.stop();
    ticket.settle(liveSession);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(harness.preview.status).toBe("finished");
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    expect(FakeLiveSocket.instances).toHaveLength(0);

    // The next recording sends its own audio only.
    void harness.start();
    (await tapped(2)).frame(7);
    ticket.settle(liveSession);
    const socket = await connected();
    socket.open();
    expect(frameTags(socket)).toEqual([7]);
  });

  it("starts each recording from empty text, and the last one's late messages add nothing", async () => {
    const harness = setup();
    const first = await listening(harness);
    first.socket.receive({ type: "transcript.delta", text: "Anna talar" });
    harness.preview.stop();

    const second = await listening(harness, 2);
    expect(texts(harness.preview)).toEqual([]);
    first.socket.receive({ type: "transcript.delta", text: " vidare" });
    first.socket.receive({ type: "transcript.done", text: "Anna talar vidare." });
    second.socket.receive({ type: "transcript.delta", text: "Bo talar" });

    expect(texts(harness.preview)).toEqual(["Bo talar"]);
  });

  it("discards the text, and a late message adds nothing back", async () => {
    const harness = setup();
    const { socket } = await listening(harness);
    socket.receive({ type: "transcript.delta", text: "Anna talar" });
    harness.preview.stop();

    harness.preview.discard();
    socket.receive({ type: "transcript.done", text: "Anna talar vidare." });

    expect(texts(harness.preview)).toEqual([]);
    expect(harness.preview.status).toBe("idle");
  });
});
