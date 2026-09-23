import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EneoError, type Eneo, type FlowLiveTranscriptionSession } from "@eneo/eneo-js";
import { LiveTranscriptPreview, type RecorderAudioGraph } from "./LiveTranscriptPreview.svelte";
import {
  FakeLiveSocket,
  FakeWorkletNode,
  installLiveTranscriptFakes,
  liveSession
} from "./liveTranscriptTestFakes";

beforeEach(() => {
  installLiveTranscriptFakes();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function setup(createSession = vi.fn(async () => liveSession)) {
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
  const start = () => preview.start(graph, { eneo, flowId: "flow-1", stepId: "step-audio" });
  return { preview, start, createSession, addModule, source };
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
    const node = FakeWorkletNode.instances[0];
    expect(harness.source.connect).toHaveBeenCalledWith(node);
    socket.receive({ type: "ready", sample_rate: 16000, max_seconds: 18000 });
    expect(harness.preview.status).toBe("listening");

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

  it("ends as interrupted with the code of an error event and sends no more audio", async () => {
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

  it("leaves the recorder's audio untouched when the ticket is refused", async () => {
    const harness = setup(
      vi.fn(async () => {
        throw new EneoError(
          "Live transcription is not available for this flow.",
          "RESPONSE",
          409,
          9057,
          {
            code: "flow_live_transcription_unavailable",
            context: { reason: "model_not_realtime" },
            eneo_error_code: 9057,
            message: "Live transcription is not available for this flow."
          }
        );
      })
    );

    await harness.start();

    expect(harness.preview.status).toBe("interrupted");
    expect(harness.preview.errorCode).toBe("model_not_realtime");
    expect(FakeLiveSocket.instances).toHaveLength(0);
    expect(harness.addModule).not.toHaveBeenCalled();
    expect(harness.source.connect).not.toHaveBeenCalled();
  });

  it("opens no socket when the recording stops before the ticket arrives", async () => {
    let issueTicket: (value: FlowLiveTranscriptionSession) => void = () => {};
    const harness = setup(vi.fn(() => new Promise((resolve) => (issueTicket = resolve))));

    const started = harness.start();
    harness.preview.stop();
    issueTicket(liveSession);
    await started;

    expect(harness.preview.status).toBe("finished");
    expect(FakeLiveSocket.instances).toHaveLength(0);
    expect(harness.source.connect).not.toHaveBeenCalled();
  });
});
