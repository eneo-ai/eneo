import { EneoError, type Eneo, type FlowLiveTranscriptionSession } from "@eneo/eneo-js";
import { PCM16_FLUSH, PCM16_FLUSHED, PCM16_PROCESSOR } from "./pcm16-worklet.js";
// A file of its own: Vite would inline a file this small as a data: URL, and
// the app's `script-src 'self'` refuses worklet modules from data: URLs.
import workletUrl from "./pcm16-worklet.js?url&no-inline";
import { generateSessionId } from "../recordingSession";

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
  | { type: "transcript.done"; text: string; transcript_id?: string }
  | { type: "error"; code: string; message: string; retryable: boolean };

const LIVE_PROTOCOL = "eneo-live.v1";
// Audio waits for the socket this long (15 s of 100 ms frames, 480 kB). A
// session that has not opened by then is unavailable; audio is never dropped.
export const MAX_QUEUED_FRAMES = 150;
// Frames are 100 ms (3.2 kB), so a socket holding this much has fallen minutes
// behind the microphone. The preview then ends visibly; it never drops audio.
const MAX_BUFFERED_BYTES = 1024 * 1024;
// The worklet answers a flush within a render quantum. One that has not
// answered by then took its last audio with it, so the stop names no count.
export const FLUSH_TIMEOUT_MS = 1_000;
// How long a run waits for the final text of a recording heard whole: measured
// at 4 s on an idle machine and over 10 s under load, against minutes for
// transcribing the audio again.
export const FINAL_TEXT_WAIT_MS = 20_000;
// A backstop just past the server's own wait for the final text (60 s).
const FINAL_TEXT_TIMEOUT_MS = 65_000;

/**
 * One owner of a step's live transcript preview: the ticket, the socket, the
 * worklet on the recorder's graph and the text shown so far. The preview is a
 * draft; the recording is uploaded as usual, so nothing here ever stops or
 * changes the recording. A dropped session is not reconnected.
 *
 * Each recording is named in its ticket request. When the session heard all of
 * it, its stop counts the samples, and Eneo's final text may name a stored
 * transcript that the run can use for the recording's one file instead of
 * transcribing it again.
 */
export class LiveTranscriptPreview {
  #status = $state<LiveTranscriptStatus>("idle");
  #pieces = $state.raw<LiveTranscriptPiece[]>([]);
  #errorCode = $state<string | null>(null);
  #stepId = $state<string | null>(null);
  #finishing = $state(false);
  // The recording's one file, once uploaded: what the run's wait depends on.
  #fileId = $state<string | null>(null);

  #socket: WebSocket | null = null;
  #node: AudioWorkletNode | null = null;
  #source: MediaStreamAudioSourceNode | null = null;
  #context: BaseAudioContext | null = null;
  #queue: ArrayBuffer[] = [];
  // The wait for the worklet's last frame, then for the final text.
  #stopTimer: ReturnType<typeof setTimeout> | undefined;
  #onListening: (() => void) | undefined;
  // Bumped whenever a session ends, so its late promises and messages are ignored.
  #generation = 0;
  #sessionText = "";
  #nextPieceId = 0;
  #recordingId: string | null = null;
  // Samples the worklet captured, counted before any wait or discard, and
  // whether this session heard the recording whole: from its first sample,
  // with nothing lost on the way. Once lost, never whole again.
  #produced = 0;
  #whole = false;
  #transcriptId: string | null = null;
  #finishingTimer: ReturnType<typeof setTimeout> | undefined;

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

  // The name the ticket request gave the recording.
  get recordingId(): string | null {
    return this.#recordingId;
  }

  // A counted stop awaits its final text, which may name a stored transcript:
  // the run waits for it, at most FINAL_TEXT_WAIT_MS.
  get finishing(): boolean {
    return this.#finishing;
  }

  // The recording's one segment is uploaded as `fileId`: its transcript goes
  // with that file only. A segment of an earlier recording changes nothing.
  recordingUploaded(recordingId: string, fileId: string): void {
    if (recordingId === this.#recordingId) this.#fileId = fileId;
  }

  // Eneo's stored transcript of the recording, when the step's files are
  // exactly the recording's one file.
  transcriptIdFor(fileIds: readonly string[]): string | undefined {
    return this.#transcriptId !== null && this.#isRecordingFile(fileIds)
      ? this.#transcriptId
      : undefined;
  }

  // The final text is still coming and could still go with the step's files.
  awaitsFinalTextFor(fileIds: readonly string[]): boolean {
    return this.#finishing && this.#isRecordingFile(fileIds);
  }

  // Some of the recording never reaches this session's transcript (it rotated
  // into a second file, or the run no longer takes one): the text stays a
  // preview, for good, and nothing waits for it.
  lose(): void {
    this.#whole = false;
    this.#transcriptId = null;
    this.#stopFinishing();
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
    this.#recordingId = generateSessionId();
    this.#produced = 0;
    this.#whole = true;
    this.#transcriptId = null;
    this.#fileId = null;

    signal?.addEventListener(
      "abort",
      () => {
        if (generation === this.#generation && !this.#node) this.#end("audio_timeout");
      },
      { once: true }
    );
    const session = eneo.flows.liveTranscription.createSession({
      id: flowId,
      stepId,
      recordingId: this.#recordingId
    });
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
    if (this.#whole) {
      this.#finishing = true;
      this.#finishingTimer = setTimeout(() => this.#stopFinishing(), FINAL_TEXT_WAIT_MS);
    }
    const node = this.#node;
    if (!node) {
      this.#sendStop(socket);
      return;
    }
    // The worklet posts its frame in progress, then PCM16_FLUSHED.
    this.#stopTimer = setTimeout(() => {
      this.lose();
      this.#sendStop(socket);
    }, FLUSH_TIMEOUT_MS);
    node.port.postMessage(PCM16_FLUSH);
  }

  // The recording was thrown away, or the preview goes: nothing of this
  // session shows again, not even a late message, and no transcript of it is
  // kept for a later recording.
  discard(): void {
    this.lose();
    this.#recordingId = null;
    this.#fileId = null;
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
    // The recorder starts in this same task. A context that is not running
    // hears none of the opening the recorder records, and one that stops
    // running later misses what the recorder goes on recording.
    if (graph.context.state !== "running") this.#whole = false;
    graph.context.addEventListener("statechange", this.#onContextState);
    this.#context = graph.context;
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
    this.#produced += frame.byteLength / 2;
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
    // A recording not heard whole names no count, and Eneo keeps no text.
    const stop = this.#whole
      ? { type: "stop", produced_samples: this.#produced }
      : { type: "stop" };
    socket.send(JSON.stringify(stop));
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
        if (this.#whole && typeof message.transcript_id === "string") {
          this.#transcriptId = message.transcript_id;
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
    this.#stopFinishing();
    this.#detachAudio();
    this.#queue = [];
    clearTimeout(this.#stopTimer);
    this.#stopTimer = undefined;
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
  }

  #onContextState = () => {
    // Only while the recording goes on: once it stops, the recorder closes its
    // context as it lets go of it, and the stop's last audio still comes, or
    // its wait times out.
    if (this.#status !== "finished" && this.#context?.state !== "running") this.lose();
  };

  #isRecordingFile(fileIds: readonly string[]): boolean {
    return fileIds.length === 1 && fileIds[0] === this.#fileId;
  }

  #stopFinishing() {
    clearTimeout(this.#finishingTimer);
    this.#finishing = false;
  }

  #detachAudio() {
    const node = this.#node;
    if (!node) return;
    this.#node = null;
    this.#context?.removeEventListener("statechange", this.#onContextState);
    this.#context = null;
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
