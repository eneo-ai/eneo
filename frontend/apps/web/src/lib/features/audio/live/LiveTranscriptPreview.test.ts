import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EneoError, type Eneo, type FlowLiveTranscriptionSession } from "@eneo/eneo-js";
import {
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

beforeEach(() => {
  installLiveTranscriptFakes();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function setup(
  createSession: () => Promise<FlowLiveTranscriptionSession> = vi.fn(async () => liveSession)
) {
  const addModule = vi.fn(async () => undefined);
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
  const start = () =>
    preview.start(graph, { eneo, flowId: "flow-1", stepId: "step-audio", onListening });
  return { preview, start, createSession, addModule, source, onListening };
}

// A ticket the test answers, so audio can arrive before it does.
function pendingTicket() {
  let issue: (session: FlowLiveTranscriptionSession) => void = () => {};
  let refuse: (error: unknown) => void = () => {};
  const request = vi.fn(
    () =>
      new Promise<FlowLiveTranscriptionSession>((resolve, reject) => {
        issue = resolve;
        refuse = reject;
      })
  );
  return { request, issue: () => issue(liveSession), refuse: (error: unknown) => refuse(error) };
}

async function tapped() {
  await vi.waitFor(() => expect(FakeWorkletNode.instances).toHaveLength(1));
  return FakeWorkletNode.instances[0];
}

function texts(preview: LiveTranscriptPreview) {
  return preview.pieces.map((piece) => piece.text);
}

async function listening(harness: ReturnType<typeof setup>) {
  await harness.start();
  const socket = FakeLiveSocket.instances[0];
  socket.open();
  socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
  return { socket, node: FakeWorkletNode.instances[0] };
}

describe("LiveTranscriptPreview", () => {
  it("keeps the recording's first words: audio waits in order until the socket opens", async () => {
    const ticket = pendingTicket();
    const harness = setup(ticket.request);
    const started = harness.start();

    const node = await tapped();
    expect(harness.source.connect).toHaveBeenCalledWith(node);
    node.frame(1);
    ticket.issue();
    await started;
    const socket = FakeLiveSocket.instances[0];
    node.frame(2);
    expect(socket.frames).toHaveLength(0);

    socket.open();
    node.frame(3);
    expect(frameTags(socket)).toEqual([1, 2, 3]);
  });

  it("streams the recorder's audio and shows the committed text until the final text", async () => {
    const harness = setup();
    const started = harness.start();
    expect(harness.preview.status).toBe("connecting");
    await started;

    const socket = FakeLiveSocket.instances[0];
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
    expect(socket.texts).toEqual([JSON.stringify({ type: "stop" })]);
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    expect(harness.preview.status).toBe("finished");
    expect(socket.close).not.toHaveBeenCalled();

    socket.receive({ type: "transcript.done", text: "Hej och välkomna." });
    expect(texts(harness.preview).join("")).toBe("Hej och välkomna.");
    expect(socket.close).toHaveBeenCalledOnce();
    expect(harness.preview.status).toBe("finished");
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
    const ticket = pendingTicket();
    const harness = setup(ticket.request);
    const started = harness.start();
    const node = await tapped();
    node.frame();

    ticket.refuse(
      new EneoError("Live transcription is not available for this flow.", "RESPONSE", 409, 9057, {
        code: "flow_live_transcription_unavailable",
        context: { reason: "model_not_realtime" },
        eneo_error_code: 9057,
        message: "Live transcription is not available for this flow."
      })
    );
    await started;

    expect(harness.preview.status).toBe("unavailable");
    expect(harness.preview.errorCode).toBe("model_not_realtime");
    expect(FakeLiveSocket.instances).toHaveLength(0);
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    expect(node.port.close).toHaveBeenCalled();
  });

  it("is unavailable, visibly, when the socket has not opened within the waiting audio's bound", async () => {
    const harness = setup();
    await harness.start();
    const socket = FakeLiveSocket.instances[0];
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
    const ticket = pendingTicket();
    const harness = setup(ticket.request);
    const started = harness.start();
    const node = await tapped();
    node.frame();

    harness.preview.stop();
    ticket.issue();
    await started;

    expect(harness.preview.status).toBe("finished");
    expect(harness.source.disconnect).toHaveBeenCalledWith(node);
    expect(FakeLiveSocket.instances).toHaveLength(0);

    // The next recording sends its own audio only.
    const restarted = harness.start();
    await vi.waitFor(() => expect(FakeWorkletNode.instances).toHaveLength(2));
    FakeWorkletNode.instances[1].frame(7);
    ticket.issue();
    await restarted;
    FakeLiveSocket.instances[0].open();
    expect(frameTags(FakeLiveSocket.instances[0])).toEqual([7]);
  });
});
