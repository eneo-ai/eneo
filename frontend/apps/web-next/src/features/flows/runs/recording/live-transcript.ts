/**
 * The live transcript of a recording in the run form: a draft the flow's
 * transcription model writes while the person records. The recording is
 * uploaded and transcribed as usual, so nothing here ever stops or changes
 * the recording.
 *
 * One owner per audio step for the ticket, the socket, the worklet on the
 * recorder's audio graph and the text so far. The protocol is the core's
 * (`flow_live_transcription_router.py`): a single-use ticket from the
 * session route, then binary frames of 16 kHz mono PCM16 and a `stop` text
 * frame; the socket answers `ready`, `transcript.delta`, `transcript.done`
 * and `error`.
 *
 * A session that heard the whole recording, from its first sample with
 * nothing lost, counts the samples in its stop, and its final text may name a
 * stored transcript the run can use instead of transcribing the recording's
 * one file again. A session that drops while the recording goes on is
 * connected again, up to three times: the text then goes on as a draft only.
 *
 * Read it from React with `useSyncExternalStore(subscribe, getSnapshot)`.
 */

/** The worklet module's processor name and messages (public/flows/pcm16-worklet.js). */
export const PCM16_PROCESSOR = "pcm16-frames";
const PCM16_FLUSH = "flush";
const PCM16_FLUSHED = "flushed";
const PCM16_PAUSE = "pause";
const PCM16_RESUME = "resume";
const PCM16_RESUMED = "resumed";
export const PCM16_WORKLET_URL = "/flows/pcm16-worklet.js";

const LIVE_PROTOCOL = "eneo-live.v1";
/** Audio waits for the socket this long (15 s of 100 ms frames) before the session gives up. */
export const MAX_QUEUED_FRAMES = 150;
/** A socket holding this much has fallen minutes behind the microphone: the session ends. */
const MAX_BUFFERED_BYTES = 1024 * 1024;
/** The worklet answers a flush within a render quantum; one that has not by then took its audio with it. */
export const FLUSH_TIMEOUT_MS = 1_000;
/** How long a run waits for the final text of a recording heard whole. */
export const FINAL_TEXT_WAIT_MS = 20_000;
/** A backstop just past the core's own wait for the final text (60 s). */
const FINAL_TEXT_TIMEOUT_MS = 65_000;
/** The waits before each new connection after a drop; then the live text stays interrupted. */
export const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000] as const;

/**
 * `unavailable`: the first session never started listening. `reconnecting`:
 * a session dropped and a new one is on its way. `interrupted`: the text
 * stopped while the recording went on.
 */
export type LiveStatus =
  "idle" | "connecting" | "listening" | "reconnecting" | "interrupted" | "unavailable" | "finished";

export type LivePiece = { id: number; text: string };

export type LiveSnapshot = {
  status: LiveStatus;
  /** Committed text, only ever appended. */
  pieces: readonly LivePiece[];
  /** The recording is paused: nothing is heard until it goes on. */
  paused: boolean;
  /** A counted stop awaits its final text, which may name a stored transcript. */
  finishing: boolean;
  /** Why the live text stopped or never started (an error code of the socket or the route). */
  errorCode: string | null;
};

/** The recorder's own graph: the live text listens to the microphone the recording uses. */
export type RecorderAudioGraph = {
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
};

export type LiveTicket = { ticket: string; websocket_path: string };

type ServerMessage =
  | { type: "ready" }
  | { type: "transcript.delta"; text: string }
  | { type: "transcript.done"; text: string; transcript_id?: string }
  | { type: "error"; code: string; message?: string; retryable?: boolean };

export type LiveTranscriptDeps = {
  /** Admits a session; `recordingId` names a recording that may be stored whole. */
  openSession: (recordingId: string | undefined) => Promise<LiveTicket>;
  /** The socket URL for the core's `websocket_path`. */
  socketUrl: (path: string) => string;
  /** Why a refused session route refused, for `errorCode`. */
  refusalReason?: (error: unknown) => string;
  createSocket?: (url: string, protocols: string[]) => WebSocket;
  createNode?: (
    context: BaseAudioContext,
    name: string,
    options: AudioWorkletNodeOptions
  ) => AudioWorkletNode;
  workletUrl?: string;
  newRecordingId?: () => string;
};

const IDLE: LiveSnapshot = {
  status: "idle",
  pieces: [],
  paused: false,
  finishing: false,
  errorCode: null
};

export class LiveTranscript {
  #snapshot: LiveSnapshot = IDLE;
  #listeners = new Set<() => void>();
  #deps: Required<Omit<LiveTranscriptDeps, "refusalReason">> &
    Pick<LiveTranscriptDeps, "refusalReason">;

  #socket: WebSocket | null = null;
  #node: AudioWorkletNode | null = null;
  #source: MediaStreamAudioSourceNode | null = null;
  #context: BaseAudioContext | null = null;
  #queue: ArrayBuffer[] = [];
  #stopTimer: ReturnType<typeof setTimeout> | undefined;
  #finishingTimer: ReturnType<typeof setTimeout> | undefined;
  #reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  #settledWaiters: (() => void)[] = [];
  /** Bumped whenever the recording's sessions end, so late promises and messages are ignored. */
  #generation = 0;
  /** Bumped per socket, so a dropped socket's late events are ignored. */
  #connection = 0;
  #reconnects = 0;
  #sessionText = "";
  #nextPieceId = 0;
  #recordingId: string | null = null;
  #produced = 0;
  #resumesUnanswered = 0;
  #whole = false;
  #transcriptId: string | null = null;

  constructor(deps: LiveTranscriptDeps) {
    this.#deps = {
      createSocket: (url, protocols) => new WebSocket(url, protocols),
      createNode: (context, name, options) => new AudioWorkletNode(context, name, options),
      workletUrl: PCM16_WORKLET_URL,
      newRecordingId: () => crypto.randomUUID(),
      ...deps
    };
  }

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  getSnapshot = (): LiveSnapshot => this.#snapshot;

  /** The name the first session's ticket gave the recording. */
  get recordingId(): string | null {
    return this.#recordingId;
  }

  /** The core's stored transcript of a recording heard whole, once its final text came. */
  get transcriptId(): string | null {
    return this.#transcriptId;
  }

  /** Settles once no final text is awaited (it came, or the wait ran out). */
  settled(): Promise<void> {
    if (!this.#snapshot.finishing) return Promise.resolve();
    return new Promise((resolve) => this.#settledWaiters.push(resolve));
  }

  /**
   * Starts the live text of a fresh recording: taps the recorder's audio and
   * connects in the background. The promise settles once the audio is tapped
   * or tapping failed; the recorder waits for it (within its own bound) so
   * the first word is heard. When the recorder stops waiting (`signal`), an
   * untapped session is unavailable and never taps late.
   */
  start(graph: RecorderAudioGraph, signal?: AbortSignal): Promise<void> {
    this.#teardown();
    const generation = this.#generation;
    this.#sessionText = "";
    this.#recordingId = this.#deps.newRecordingId();
    this.#produced = 0;
    this.#resumesUnanswered = 0;
    this.#reconnects = 0;
    this.#whole = true;
    this.#transcriptId = null;
    this.#set({ ...IDLE, status: "connecting" });

    signal?.addEventListener(
      "abort",
      () => {
        if (generation === this.#generation && !this.#node) this.#end("audio_timeout");
      },
      { once: true }
    );
    const ticket = this.#deps.openSession(this.#recordingId);
    // Rejections are handled where each promise is awaited; this keeps an
    // early one from being reported as unhandled meanwhile.
    ticket.catch(() => undefined);
    const tapped = graph.context.audioWorklet.addModule(this.#deps.workletUrl).then(() => {
      if (generation === this.#generation) this.#tap(graph);
    });
    void this.#connect(generation, ticket, tapped);
    return tapped.catch(() => undefined);
  }

  /**
   * The recording paused (true) or went on: what the microphone hears
   * meanwhile is not recorded, so it is not sent. The text then no longer
   * matches the recording exactly: it stays a draft.
   */
  pause(paused: boolean): void {
    this.#set({ ...this.#snapshot, paused });
    const node = this.#node;
    if (paused) {
      node?.port.postMessage(PCM16_PAUSE);
      this.lose();
    } else if (node) {
      // Frames stay closed out until the worklet answers: until then they may
      // hold what it heard before it handled the pause.
      this.#resumesUnanswered += 1;
      node.port.postMessage(PCM16_RESUME);
    }
  }

  /**
   * Some of the recording never reaches this text (it went on in a second
   * part, or a session dropped): the text stays a draft, for good, and
   * nothing waits for it.
   */
  lose(): void {
    this.#whole = false;
    this.#transcriptId = null;
    this.#stopFinishing();
  }

  /**
   * The recording ended: send what is left of its audio, then ask for the
   * rest of the text and keep the socket until it arrives. Called while the
   * recorder releases its graph, so it neither waits nor throws.
   */
  stop(): void {
    const { status } = this.#snapshot;
    if (status === "idle" || status === "finished") return;
    const socket = this.#socket;
    const awaitsFinalText = status === "listening" && socket?.readyState === WebSocket.OPEN;
    if (this.#context && this.#context.state !== "running") this.lose();
    clearTimeout(this.#reconnectTimer);
    this.#set({ ...this.#snapshot, status: "finished" });
    if (!socket || !awaitsFinalText) {
      this.#teardown();
      return;
    }
    if (this.#whole) {
      this.#set({ ...this.#snapshot, finishing: true });
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

  /** The recording was thrown away: nothing of it shows again, not even a late message. */
  discard(): void {
    this.lose();
    this.#recordingId = null;
    this.#teardown();
    this.#set(IDLE);
  }

  async #connect(generation: number, ticket: Promise<LiveTicket>, tapped: Promise<void>) {
    try {
      const [admitted] = await Promise.all([ticket, tapped]);
      if (generation !== this.#generation) return;
      this.#open(admitted);
    } catch (error) {
      if (generation === this.#generation) this.#end(this.#refusal(error));
    }
  }

  #open(ticket: LiveTicket) {
    const connection = ++this.#connection;
    const socket = this.#deps.createSocket(this.#deps.socketUrl(ticket.websocket_path), [
      LIVE_PROTOCOL,
      `ticket.${ticket.ticket}`
    ]);
    socket.binaryType = "arraybuffer";
    this.#socket = socket;
    this.#sessionText = "";
    const current = () => connection === this.#connection && socket === this.#socket;
    socket.onopen = () => {
      if (current()) this.#flush(socket);
    };
    socket.onmessage = (event: MessageEvent) => {
      if (!current() || typeof event.data !== "string") return;
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        return;
      }
      this.#receive(message);
    };
    socket.onclose = () => {
      if (current()) this.#dropped("connection_closed", true);
    };
  }

  #tap(graph: RecorderAudioGraph) {
    // A context that is not running hears none of the opening the recorder records.
    if (graph.context.state !== "running") this.#whole = false;
    const node = this.#deps.createNode(graph.context, PCM16_PROCESSOR, {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      channelCountMode: "explicit",
      channelInterpretation: "speakers"
    });
    node.port.onmessage = (event: MessageEvent<ArrayBuffer | string>) => {
      if (event.data === PCM16_RESUMED) {
        this.#resumesUnanswered -= 1;
      } else if (event.data === PCM16_FLUSHED) {
        if (this.#socket) this.#sendStop(this.#socket);
      } else if (event.data instanceof ArrayBuffer) {
        this.#takeFrame(event.data);
      }
    };
    graph.source.connect(node);
    this.#node = node;
    this.#source = graph.source;
    graph.context.addEventListener("statechange", this.#onContextState);
    this.#context = graph.context;
  }

  #takeFrame(frame: ArrayBuffer) {
    if (this.#snapshot.paused || this.#resumesUnanswered > 0) return;
    this.#produced += frame.byteLength / 2;
    const socket = this.#socket;
    if (socket?.readyState === WebSocket.OPEN && this.#snapshot.status !== "reconnecting") {
      this.#send(socket, frame);
      return;
    }
    if (this.#queue.length === MAX_QUEUED_FRAMES) {
      if (this.#snapshot.status !== "reconnecting") {
        this.#end("connect_timeout");
        return;
      }
      // The text has a gap already: what waits longest goes first.
      this.#queue.shift();
    }
    this.#queue.push(frame);
  }

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
    // A recording not heard whole names no count, and the core keeps no text.
    const stop = this.#whole
      ? { type: "stop", produced_samples: this.#produced }
      : { type: "stop" };
    socket.send(JSON.stringify(stop));
    this.#stopTimer = setTimeout(() => this.#teardown(), FINAL_TEXT_TIMEOUT_MS);
  }

  #receive(message: ServerMessage) {
    switch (message.type) {
      case "ready": {
        const { status } = this.#snapshot;
        if (status !== "connecting" && status !== "reconnecting") return;
        if (status === "reconnecting" && this.#socket) this.#flush(this.#socket);
        this.#set({ ...this.#snapshot, status: "listening", errorCode: null });
        return;
      }
      case "transcript.delta":
        this.#append(message.text);
        return;
      case "transcript.done":
        // The session's whole text: normally the deltas hold it already.
        if (message.text.startsWith(this.#sessionText)) {
          this.#append(message.text.slice(this.#sessionText.length));
        }
        if (this.#whole && typeof message.transcript_id === "string") {
          this.#transcriptId = message.transcript_id;
        }
        this.#end("session_ended");
        return;
      case "error":
        this.#dropped(message.code, message.retryable === true);
    }
  }

  #append(text: string) {
    if (!text) return;
    const pieces = this.#snapshot.pieces;
    const previous = pieces.at(-1)?.text ?? "";
    // A new session after a drop starts its text afresh: keep the words apart.
    const joined =
      this.#sessionText === "" && previous !== "" && !/\s$/.test(previous) && !/^\s/.test(text)
        ? ` ${text}`
        : text;
    this.#sessionText += text;
    this.#set({
      ...this.#snapshot,
      pieces: [...pieces, { id: this.#nextPieceId++, text: joined }]
    });
  }

  /** A session ended early: connect again while the recording goes on, or end. */
  #dropped(code: string, retryable: boolean) {
    const { status } = this.#snapshot;
    const recordingGoesOn = status === "listening" || status === "reconnecting";
    if (!retryable || !recordingGoesOn || this.#reconnects >= RECONNECT_DELAYS_MS.length) {
      this.#end(code);
      return;
    }
    // What the dropped session missed never reaches this text.
    this.lose();
    const socket = this.#socket;
    this.#socket = null;
    this.#connection += 1;
    socket?.close();
    const generation = this.#generation;
    const delay = RECONNECT_DELAYS_MS[this.#reconnects] ?? 0;
    this.#reconnects += 1;
    this.#set({ ...this.#snapshot, status: "reconnecting", errorCode: code });
    clearTimeout(this.#reconnectTimer);
    this.#reconnectTimer = setTimeout(() => {
      if (generation !== this.#generation) return;
      const ticket = this.#deps.openSession(undefined);
      ticket.then(
        (admitted) => {
          if (generation !== this.#generation || this.#snapshot.status !== "reconnecting") return;
          this.#open(admitted);
        },
        (error: unknown) => {
          if (generation !== this.#generation || this.#snapshot.status !== "reconnecting") return;
          this.#dropped(this.#refusal(error), true);
        }
      );
    }, delay);
  }

  /** The sessions are over: say whether the text never got going or stopped; the text stays. */
  #end(code: string) {
    const { status } = this.#snapshot;
    if (status === "connecting") {
      this.#set({ ...this.#snapshot, status: "unavailable", errorCode: code });
    } else if (status === "listening" || status === "reconnecting") {
      this.#set({ ...this.#snapshot, status: "interrupted", errorCode: code });
    }
    this.#teardown();
  }

  #teardown() {
    this.#generation += 1;
    this.#connection += 1;
    this.#stopFinishing();
    this.#detachAudio();
    this.#queue = [];
    clearTimeout(this.#stopTimer);
    clearTimeout(this.#reconnectTimer);
    this.#stopTimer = undefined;
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
  }

  #onContextState = () => {
    // Only while the recording goes on: once it stops, the recorder closes its context.
    if (this.#snapshot.status !== "finished" && this.#context?.state !== "running") this.lose();
  };

  #stopFinishing() {
    clearTimeout(this.#finishingTimer);
    if (this.#snapshot.finishing) this.#set({ ...this.#snapshot, finishing: false });
    for (const resolve of this.#settledWaiters.splice(0)) resolve();
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

  #refusal(error: unknown): string {
    return this.#deps.refusalReason?.(error) ?? "unavailable";
  }

  #set(next: LiveSnapshot) {
    this.#snapshot = next;
    for (const listener of this.#listeners) listener();
  }
}
