import { EneoError, type Eneo, type FlowLiveTranscriptionSession } from "@eneo/eneo-js";
import { PCM16_FLUSH, PCM16_FLUSHED, PCM16_PROCESSOR } from "./pcm16-worklet.js";
// A file of its own: Vite would inline a file this small as a data: URL, and
// the app's `script-src 'self'` refuses worklet modules from data: URLs.
import workletUrl from "./pcm16-worklet.js?url&no-inline";

// "unavailable": the session never reached listening. "interrupted": it was
// listening and ended while the recording went on.
export type LiveTranscriptStatus =
  "idle" | "connecting" | "listening" | "interrupted" | "unavailable" | "finished";

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
// Audio waits for the socket this long (15 s of 100 ms frames, 480 kB). A
// session that has not opened by then is unavailable; audio is never dropped.
export const MAX_QUEUED_FRAMES = 150;
// Frames are 100 ms (3.2 kB), so a socket holding this much has fallen minutes
// behind the microphone. The preview then ends visibly; it never drops audio.
const MAX_BUFFERED_BYTES = 1024 * 1024;
// The worklet answers a flush within a render quantum; the bound only covers a
// worklet that cannot answer any more because the recorder closed its context.
export const FLUSH_TIMEOUT_MS = 200;
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
  #queue: ArrayBuffer[] = [];
  // The wait for the worklet's last frame, then for the final text.
  #stopTimer: ReturnType<typeof setTimeout> | undefined;
  #onListening: (() => void) | undefined;
  // Bumped whenever a session ends, so its late promises and messages are ignored.
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

  /**
   * Starts the preview of a fresh recording: taps the recorder's audio and
   * connects in the background. The promise settles once the audio is tapped
   * or tapping failed; the recorder waits for it, within its own bound, before
   * it records, so the preview hears the first word. When the recorder stops
   * waiting (`signal`), an untapped preview is unavailable and never taps late.
   */
  start(
    graph: RecorderAudioGraph,
    {
      eneo,
      flowId,
      stepId,
      onListening,
      signal
    }: {
      eneo: Eneo;
      flowId: string;
      stepId: string;
      onListening?: () => void;
      signal?: AbortSignal;
    }
  ): Promise<void> {
    this.#teardown();
    const generation = this.#generation;
    this.#pieces = [];
    this.#stepId = stepId;
    this.#status = "connecting";
    this.#errorCode = null;
    this.#sessionText = "";
    this.#onListening = onListening;

    signal?.addEventListener(
      "abort",
      () => {
        if (generation === this.#generation && !this.#node) this.#end("audio_timeout");
      },
      { once: true }
    );
    const session = eneo.flows.liveTranscription.createSession({ id: flowId, stepId });
    const tapped = graph.context.audioWorklet.addModule(workletUrl).then(() => {
      if (generation === this.#generation) this.#tap(graph);
    });
    void this.#connect(generation, eneo, session, tapped);
    return tapped.catch(() => undefined);
  }

  // The recording ended: send what is left of its audio, then ask for the
  // rest of the text and keep the socket until it arrives. The recorder calls
  // this while releasing its graph, so it neither waits nor throws.
  stop(): void {
    if (this.#status === "idle" || this.#status === "finished") return;
    const socket = this.#socket;
    const awaitsFinalText = this.#status === "listening" && socket?.readyState === WebSocket.OPEN;
    // A notice about the recording going on is no longer true.
    this.#status = "finished";
    if (!socket || !awaitsFinalText) {
      this.#teardown();
      return;
    }
    const node = this.#node;
    if (!node) {
      this.#sendStop(socket);
      return;
    }
    // The worklet posts its frame in progress, then PCM16_FLUSHED.
    this.#stopTimer = setTimeout(() => this.#sendStop(socket), FLUSH_TIMEOUT_MS);
    node.port.postMessage(PCM16_FLUSH);
  }

  // The recording was thrown away, or the preview goes: nothing of this
  // session shows again, not even a late message.
  discard(): void {
    this.#teardown();
    this.#pieces = [];
    this.#status = "idle";
    this.#errorCode = null;
  }

  async #connect(
    generation: number,
    eneo: Eneo,
    session: Promise<FlowLiveTranscriptionSession>,
    tapped: Promise<void>
  ) {
    try {
      const [ticket] = await Promise.all([session, tapped]);
      if (generation !== this.#generation) return;

      const socket = new WebSocket(liveSocketUrl(eneo.client.baseUrl, ticket.websocket_path), [
        LIVE_PROTOCOL,
        `ticket.${ticket.ticket}`
      ]);
      this.#socket = socket;
      socket.onopen = () => {
        if (socket === this.#socket) this.#flush(socket);
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

  // Mono in, no output: nothing of the microphone reaches the speakers.
  #tap(graph: RecorderAudioGraph) {
    const node = new AudioWorkletNode(graph.context, PCM16_PROCESSOR, {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      channelCountMode: "explicit",
      channelInterpretation: "speakers"
    });
    node.port.onmessage = (event: MessageEvent<ArrayBuffer | string>) => {
      if (event.data !== PCM16_FLUSHED) {
        this.#takeFrame(event.data as ArrayBuffer);
      } else if (this.#socket) {
        this.#sendStop(this.#socket);
      }
    };
    graph.source.connect(node);
    this.#node = node;
    this.#source = graph.source;
  }

  #takeFrame(frame: ArrayBuffer) {
    const socket = this.#socket;
    if (socket?.readyState === WebSocket.OPEN) {
      this.#send(socket, frame);
      return;
    }
    if (this.#queue.length === MAX_QUEUED_FRAMES) {
      this.#end("connect_timeout");
      return;
    }
    this.#queue.push(frame);
  }

  // The waiting audio goes first, in order, then the live frames follow.
  #flush(socket: WebSocket) {
    for (const frame of this.#queue.splice(0)) {
      if (!this.#send(socket, frame)) return;
    }
  }

  #send(socket: WebSocket, frame: ArrayBuffer): boolean {
    if (socket.bufferedAmount + frame.byteLength > MAX_BUFFERED_BYTES) {
      this.#end("backpressure");
      return false;
    }
    socket.send(frame);
    return true;
  }

  #sendStop(socket: WebSocket) {
    clearTimeout(this.#stopTimer);
    this.#detachAudio();
    if (socket !== this.#socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "stop" }));
    this.#stopTimer = setTimeout(() => this.#teardown(), FINAL_TEXT_TIMEOUT_MS);
  }

  #receive(message: LiveServerMessage) {
    switch (message.type) {
      case "ready":
        if (this.#status !== "connecting") return;
        this.#status = "listening";
        this.#onListening?.();
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

  // The session is over while the recording goes on: the user is told whether
  // live text never got going or stopped, and the text so far stays.
  #end(code: string) {
    if (this.#status === "connecting" || this.#status === "listening") {
      this.#status = this.#status === "connecting" ? "unavailable" : "interrupted";
      this.#errorCode = code;
    }
    this.#teardown();
  }

  #teardown() {
    this.#generation += 1;
    this.#detachAudio();
    this.#queue = [];
    clearTimeout(this.#stopTimer);
    this.#stopTimer = undefined;
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
