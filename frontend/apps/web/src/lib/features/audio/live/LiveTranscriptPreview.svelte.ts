import { EneoError, type Eneo } from "@eneo/eneo-js";
import { PCM16_PROCESSOR } from "./pcm16-worklet.js";
// A file of its own: Vite would inline a file this small as a data: URL, and
// the app's `script-src 'self'` refuses worklet modules from data: URLs.
import workletUrl from "./pcm16-worklet.js?url&no-inline";

export type LiveTranscriptStatus = "idle" | "connecting" | "listening" | "interrupted" | "finished";

// The recorder's own graph: the preview listens to the microphone the
// recording already uses, on the context that already runs at its rate.
export type RecorderAudioGraph = {
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
};

export type LiveTranscriptPiece = { id: number; text: string };

type LiveServerMessage =
  | { type: "ready"; sample_rate: number; max_seconds: number }
  | { type: "transcript.delta"; text: string }
  | { type: "transcript.done"; text: string }
  | { type: "error"; code: string; message: string; retryable: boolean };

const LIVE_PROTOCOL = "eneo-live.v1";
// Frames are 100 ms (3.2 kB), so a socket holding this much has fallen minutes
// behind the microphone. The preview then ends visibly; it never drops audio.
const MAX_BUFFERED_BYTES = 1024 * 1024;
// A backstop just past the server's own wait for the final text (60 s).
const FINAL_TEXT_TIMEOUT_MS = 65_000;

/**
 * One owner of a step's live transcript preview: the ticket, the socket, the
 * worklet on the recorder's graph and the text shown so far. The preview is a
 * draft; the recording is uploaded and transcribed as usual, so nothing here
 * ever stops or changes the recording. A dropped session is not reconnected.
 */
export class LiveTranscriptPreview {
  #status = $state<LiveTranscriptStatus>("idle");
  #pieces = $state.raw<LiveTranscriptPiece[]>([]);
  #errorCode = $state<string | null>(null);
  #stepId = $state<string | null>(null);

  #socket: WebSocket | null = null;
  #node: AudioWorkletNode | null = null;
  #source: MediaStreamAudioSourceNode | null = null;
  #finalTextTimer: ReturnType<typeof setTimeout> | undefined;
  // Bumped whenever a session ends, so a start still awaiting its ticket or
  // worklet knows it was overtaken.
  #generation = 0;
  #sessionText = "";
  #nextPieceId = 0;

  get status(): LiveTranscriptStatus {
    return this.#status;
  }

  get pieces(): readonly LiveTranscriptPiece[] {
    return this.#pieces;
  }

  get errorCode(): string | null {
    return this.#errorCode;
  }

  // The step whose recording the text belongs to.
  get stepId(): string | null {
    return this.#stepId;
  }

  async start(
    graph: RecorderAudioGraph,
    { eneo, flowId, stepId }: { eneo: Eneo; flowId: string; stepId: string }
  ): Promise<void> {
    this.#teardown();
    const generation = this.#generation;
    if (this.#stepId !== stepId) this.#pieces = [];
    this.#stepId = stepId;
    this.#status = "connecting";
    this.#errorCode = null;
    this.#sessionText = "";

    try {
      const session = await eneo.flows.liveTranscription.createSession({ id: flowId, stepId });
      await graph.context.audioWorklet.addModule(workletUrl);
      if (generation !== this.#generation) return;

      const socket = new WebSocket(liveSocketUrl(eneo.client.baseUrl, session.websocket_path), [
        LIVE_PROTOCOL,
        `ticket.${session.ticket}`
      ]);
      this.#socket = socket;
      socket.onopen = () => {
        if (socket === this.#socket) this.#listen(socket, graph);
      };
      socket.onmessage = (event: MessageEvent) => {
        if (socket === this.#socket && typeof event.data === "string") {
          this.#receive(JSON.parse(event.data) as LiveServerMessage);
        }
      };
      socket.onclose = () => {
        if (socket === this.#socket) this.#end("connection_closed");
      };
    } catch (error) {
      if (generation === this.#generation) this.#end(refusalReason(error));
    }
  }

  // The recording ended: ask for the rest of the text and keep the socket
  // until it arrives. The recorder calls this while releasing its graph, so it
  // must not throw.
  stop(): void {
    if (this.#status !== "connecting" && this.#status !== "listening") return;
    const socket = this.#socket;
    const awaitsFinalText = this.#status === "listening" && socket?.readyState === WebSocket.OPEN;
    this.#status = "finished";
    if (!socket || !awaitsFinalText) {
      this.#teardown();
      return;
    }
    this.#detachAudio();
    socket.send(JSON.stringify({ type: "stop" }));
    this.#finalTextTimer = setTimeout(() => this.#teardown(), FINAL_TEXT_TIMEOUT_MS);
  }

  dispose(): void {
    this.#teardown();
  }

  #listen(socket: WebSocket, graph: RecorderAudioGraph) {
    try {
      // Mono in, no output: nothing of the microphone reaches the speakers.
      const node = new AudioWorkletNode(graph.context, PCM16_PROCESSOR, {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        channelCount: 1,
        channelCountMode: "explicit",
        channelInterpretation: "speakers"
      });
      node.port.onmessage = (event: MessageEvent<ArrayBuffer>) =>
        this.#sendFrame(socket, event.data);
      graph.source.connect(node);
      this.#node = node;
      this.#source = graph.source;
    } catch {
      this.#end("audio_unavailable");
    }
  }

  #sendFrame(socket: WebSocket, frame: ArrayBuffer) {
    if (socket !== this.#socket || socket.readyState !== WebSocket.OPEN) return;
    if (socket.bufferedAmount + frame.byteLength > MAX_BUFFERED_BYTES) {
      this.#end("backpressure");
      return;
    }
    socket.send(frame);
  }

  #receive(message: LiveServerMessage) {
    switch (message.type) {
      case "ready":
        if (this.#status === "connecting") this.#status = "listening";
        return;
      case "transcript.delta":
        this.#append(message.text);
        return;
      case "transcript.done":
        // The whole session's text: normally the deltas already hold it, and
        // text that was never sent as a delta is added at the end.
        if (message.text.startsWith(this.#sessionText)) {
          this.#append(message.text.slice(this.#sessionText.length));
        }
        this.#end("session_ended");
        return;
      case "error":
        this.#end(message.code);
    }
  }

  #append(text: string) {
    if (!text) return;
    this.#sessionText += text;
    this.#pieces = [...this.#pieces, { id: this.#nextPieceId++, text }];
  }

  // The session is over. While recording goes on, that is an interruption the
  // user is told about; the text so far stays.
  #end(code: string) {
    if (this.#status === "connecting" || this.#status === "listening") {
      this.#status = "interrupted";
      this.#errorCode = code;
    }
    this.#teardown();
  }

  #teardown() {
    this.#generation += 1;
    this.#detachAudio();
    clearTimeout(this.#finalTextTimer);
    this.#finalTextTimer = undefined;
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
  }

  #detachAudio() {
    const node = this.#node;
    if (!node) return;
    this.#node = null;
    node.port.onmessage = null;
    node.port.close();
    try {
      this.#source?.disconnect(node);
    } catch {
      // The recorder already took its graph down.
    }
    this.#source = null;
  }
}

// On the API host, like the app's own socket; local development runs without TLS.
function liveSocketUrl({ protocol, host }: URL, path: string): string {
  return `${protocol === "http:" ? "ws:" : "wss:"}//${host}${path}`;
}

function refusalReason(error: unknown): string {
  const reason = error instanceof EneoError ? error.response?.context?.reason : undefined;
  return typeof reason === "string" ? reason : "unavailable";
}
