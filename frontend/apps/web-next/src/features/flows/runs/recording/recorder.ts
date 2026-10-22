import { partFileName, recordingTimeLeftMs, type RecordingOptions } from "./recording-format";
import type { RecorderAudioGraph } from "./live-transcript";
import { withRecordedDuration } from "./webm-duration";

/**
 * One microphone recording in the run form, from the permission prompt to
 * the last part's file. A long recording goes on in parts, each a file of
 * its own, at the length the run contract asks for; it stops by itself at
 * the step's longest recording or when no file slot is left for another
 * part, and when the microphone goes away (what was recorded is kept, and
 * recording again continues the same recording).
 *
 * The recorded clock leaves the person's pauses out. Parts are handed over
 * in recording order, each with the recorded duration written into its
 * header so a player can seek in it.
 *
 * Read it from React with `useSyncExternalStore(subscribe, getSnapshot)`.
 */

export type RecorderPhase = "idle" | "starting" | "recording" | "paused" | "stopping";

/** Why a recording could not start. */
export type RecorderProblem =
  | "unsupported"
  | "insecure"
  | "permission_denied"
  | "no_microphone"
  | "microphone_busy"
  | "microphone_failed";

/** Why the last recording stopped. */
export type RecordingEnd = "manual" | "length" | "files" | "device_lost" | "error";

export type RecorderSnapshot = {
  phase: RecorderPhase;
  problem: RecorderProblem | null;
  ended: RecordingEnd | null;
  /** Recorded time of this recording, pauses left out, as of the last change. */
  recordedMs: number;
  /** Wall-clock time at which a running clock would have read zero; null unless recording. */
  clockStartedAt: number | null;
  /** Whole minutes left before the longest recording, once ten or fewer remain. */
  minutesLeft: number | null;
};

export type RecordedPart = {
  file: File;
  sessionId: string;
  index: number;
  durationMs: number;
};

/** What the step lets this recording take, read when it starts and on every tick. */
export type RecorderLimits = {
  partMs: number | null;
  maxRecordingMs: number | null;
  /** Recorded time and parts of the same recording from before this start. */
  recordedBeforeMs: number;
  partsBefore: number;
  /** Free file slots of the step, not counting what this recording has yet to hand over. */
  filesLeft: number;
};

export type StartOptions = {
  sessionId: string;
  firstIndex: number;
  limits: () => RecorderLimits;
};

export type RecorderCallbacks = {
  /** A finished part, in recording order. */
  onPart: (part: RecordedPart) => void;
  /**
   * The microphone's audio graph once it is open, and null as the recording
   * stops. A pending promise holds the start back, at most
   * GRAPH_PREPARATION_MS; `signal` aborts once the start stops waiting.
   */
  onAudioGraph?: (graph: RecorderAudioGraph | null, signal?: AbortSignal) => void | Promise<void>;
  onPause?: (paused: boolean) => void;
  /** The recording is about to go on in a new part: the live text no longer covers one file. */
  onRotate?: () => void;
};

type RecorderEnvironment = {
  mediaDevices: Pick<MediaDevices, "getUserMedia"> | undefined;
  MediaRecorder: typeof MediaRecorder | undefined;
  AudioContext: typeof AudioContext | undefined;
  isSecureContext: boolean;
  wakeLock: { request(type: "screen"): Promise<{ release(): Promise<void> }> } | undefined;
  /** A monotonic clock: a system clock set during a meeting must not change the recording. */
  now: () => number;
  wallNow: () => number;
};

export function browserEnvironment(): RecorderEnvironment {
  const nav = typeof navigator === "undefined" ? undefined : navigator;
  return {
    mediaDevices: nav?.mediaDevices,
    MediaRecorder: typeof MediaRecorder === "undefined" ? undefined : MediaRecorder,
    AudioContext: typeof AudioContext === "undefined" ? undefined : AudioContext,
    isSecureContext: typeof window === "undefined" ? true : window.isSecureContext,
    wakeLock: (nav as (Navigator & { wakeLock?: RecorderEnvironment["wakeLock"] }) | undefined)
      ?.wakeLock,
    now: () => performance.now(),
    wallNow: () => Date.now()
  };
}

/** Whether this browser can record here at all, or why not. */
export function recordingSupport(
  environment: Pick<RecorderEnvironment, "mediaDevices" | "MediaRecorder" | "isSecureContext">
): "supported" | "insecure" | "unsupported" {
  // Browsers hide the microphone from pages not served over https.
  if (!environment.isSecureContext) return "insecure";
  if (!environment.mediaDevices?.getUserMedia || !environment.MediaRecorder) return "unsupported";
  return "supported";
}

/** How long a start waits for a listener preparing on the audio graph. */
export const GRAPH_PREPARATION_MS = 2_000;
/** Chunks arrive this often, so a part's audio is never all in the encoder. */
const TIMESLICE_MS = 1_000;
/**
 * The replaced recorder keeps capturing this long after the next one starts
 * (Chromium drops the last tens of milliseconds before stop()), so the parts
 * overlap instead of leaving a gap.
 */
export const ROTATION_OVERLAP_MS = 150;
const TICK_MS = 500;

function problemOf(error: unknown): RecorderProblem {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "PermissionDeniedError":
    case "SecurityError":
      return "permission_denied";
    case "NotFoundError":
    case "DevicesNotFoundError":
    case "OverconstrainedError":
      return "no_microphone";
    case "NotReadableError":
    case "TrackStartError":
    case "AbortError":
      return "microphone_busy";
    default:
      return "microphone_failed";
  }
}

type Part = {
  recorder: MediaRecorder;
  index: number;
  chunks: Blob[];
  /** Recorded time (the recording's clock) at which this part started. */
  startedAtMs: number;
  /** Wall-clock time at which it started, which its file name carries. */
  capturedAt: number;
  /** Settles once the part was handed over (or found empty). */
  handedOver: Promise<void>;
};

const IDLE: RecorderSnapshot = {
  phase: "idle",
  problem: null,
  ended: null,
  recordedMs: 0,
  clockStartedAt: null,
  minutesLeft: null
};

export class AudioRecorder {
  #snapshot: RecorderSnapshot = IDLE;
  #listeners = new Set<() => void>();
  #env: RecorderEnvironment;
  #options: RecordingOptions;
  #callbacks: RecorderCallbacks;

  #stream: MediaStream | null = null;
  #context: AudioContext | null = null;
  #wakeLock: { release(): Promise<void> } | null = null;
  #part: Part | null = null;
  #handovers: Promise<void> = Promise.resolve();
  #pendingHandovers = 0;
  #session: StartOptions | null = null;
  #nextIndex = 0;
  #partsThisStart = 0;
  #tick: ReturnType<typeof setInterval> | undefined;
  /** The recorded clock: monotonic time since the start, pauses left out. */
  #clockStartedAt = 0;
  #pausedAt: number | null = null;
  #pausedTotal = 0;
  #disposed = false;
  #attempt = 0;

  constructor(
    options: RecordingOptions,
    callbacks: RecorderCallbacks,
    environment: RecorderEnvironment = browserEnvironment()
  ) {
    this.#options = options;
    this.#callbacks = callbacks;
    this.#env = environment;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  getSnapshot = (): RecorderSnapshot => this.#snapshot;

  /** Parts started but not handed over yet, the running one included: each will take a file slot. */
  get pendingParts(): number {
    return this.#pendingHandovers;
  }

  /** Recorded time so far, pauses left out. */
  recordedMs(): number {
    if (this.#snapshot.phase === "idle" || this.#snapshot.phase === "starting") return 0;
    return (this.#pausedAt ?? this.#env.now()) - this.#clockStartedAt - this.#pausedTotal;
  }

  /** Asks for the microphone and records; a refusal is told in `problem`. */
  async start(options: StartOptions): Promise<void> {
    if (this.#snapshot.phase !== "idle" || this.#disposed) return;
    const support = recordingSupport(this.#env);
    if (support !== "supported") {
      this.#set({ ...IDLE, problem: support });
      return;
    }
    const attempt = ++this.#attempt;
    this.#session = options;
    this.#nextIndex = options.firstIndex;
    this.#partsThisStart = 0;
    this.#set({ ...IDLE, phase: "starting" });

    let stream: MediaStream;
    try {
      stream = await this.#env.mediaDevices!.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1
        }
      });
    } catch (error) {
      if (attempt === this.#attempt) this.#set({ ...IDLE, problem: problemOf(error) });
      return;
    }
    if (attempt !== this.#attempt || this.#disposed) {
      for (const track of stream.getTracks()) track.stop();
      return;
    }
    this.#stream = stream;
    for (const track of stream.getAudioTracks()) {
      track.addEventListener("ended", this.#onTrackEnded);
    }

    await this.#offerGraph(stream);
    if (attempt !== this.#attempt || this.#disposed) {
      this.#callbacks.onAudioGraph?.(null);
      this.#release();
      return;
    }

    this.#clockStartedAt = this.#env.now();
    this.#pausedAt = null;
    this.#pausedTotal = 0;
    if (!this.#startPart()) {
      this.#callbacks.onAudioGraph?.(null);
      this.#release();
      this.#set({ ...IDLE, problem: "microphone_failed" });
      return;
    }
    this.#holdWakeLock();
    this.#tick = setInterval(this.#onTick, TICK_MS);
    this.#set({
      ...IDLE,
      phase: "recording",
      clockStartedAt: this.#env.wallNow(),
      minutesLeft: this.#minutesLeft()
    });
  }

  pause(): void {
    if (this.#snapshot.phase !== "recording" || !this.#part) return;
    try {
      this.#part.recorder.pause();
    } catch {
      return;
    }
    this.#pausedAt = this.#env.now();
    this.#set({
      ...this.#snapshot,
      phase: "paused",
      recordedMs: this.recordedMs(),
      clockStartedAt: null
    });
    this.#callbacks.onPause?.(true);
  }

  resume(): void {
    if (this.#snapshot.phase !== "paused" || !this.#part) return;
    try {
      this.#part.recorder.resume();
    } catch {
      this.stop("error");
      return;
    }
    if (this.#pausedAt !== null) this.#pausedTotal += this.#env.now() - this.#pausedAt;
    this.#pausedAt = null;
    const recorded = this.recordedMs();
    this.#set({
      ...this.#snapshot,
      phase: "recording",
      recordedMs: recorded,
      clockStartedAt: this.#env.wallNow() - recorded
    });
    this.#callbacks.onPause?.(false);
  }

  /** Stops the recording; its last part is handed over a moment later. */
  stop(reason: RecordingEnd = "manual"): Promise<void> {
    const { phase } = this.#snapshot;
    if (phase === "starting") {
      // The prompt is still open: whatever it answers is not recorded.
      this.#attempt += 1;
      this.#set({ ...IDLE });
      return Promise.resolve();
    }
    if (phase !== "recording" && phase !== "paused") return this.#handovers;
    const recorded = this.recordedMs();
    // The clock stops here: the last part's length is what was recorded until now.
    this.#pausedAt ??= this.#env.now();
    clearInterval(this.#tick);
    this.#set({ ...this.#snapshot, phase: "stopping", recordedMs: recorded, clockStartedAt: null });
    // The live text gets its last audio while the graph is still there.
    this.#callbacks.onAudioGraph?.(null);
    const part = this.#part;
    this.#part = null;
    if (part) this.#stopPart(part);
    const done = this.#handovers.then(() => {
      this.#release();
      this.#set({ ...IDLE, ended: reason, recordedMs: recorded });
    });
    return done;
  }

  /** Lets go of the microphone at once; nothing more is handed over. */
  dispose(): void {
    this.#disposed = true;
    this.#attempt += 1;
    clearInterval(this.#tick);
    const part = this.#part;
    this.#part = null;
    if (part) {
      part.recorder.ondataavailable = null;
      part.recorder.onstop = null;
      try {
        part.recorder.stop();
      } catch {
        // Already stopped.
      }
    }
    this.#callbacks.onAudioGraph?.(null);
    this.#release();
    this.#listeners.clear();
  }

  /** Clears why the last recording could not start or stopped by itself. */
  dismiss(): void {
    if (this.#snapshot.phase !== "idle") return;
    this.#set({ ...IDLE });
  }

  async #offerGraph(stream: MediaStream) {
    const Context = this.#env.AudioContext;
    if (!Context || !this.#callbacks.onAudioGraph) return;
    let graph: RecorderAudioGraph;
    try {
      const context = new Context();
      this.#context = context;
      graph = { context, source: context.createMediaStreamSource(stream) };
    } catch {
      // No audio graph: the recording goes on without live text.
      return;
    }
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.resolve(this.#callbacks.onAudioGraph(graph, abort.signal)).catch(() => undefined),
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, GRAPH_PREPARATION_MS);
        })
      ]);
    } finally {
      clearTimeout(timer);
      abort.abort();
    }
  }

  #startPart(): boolean {
    const Recorder = this.#env.MediaRecorder;
    const stream = this.#stream;
    if (!Recorder || !stream) return false;
    let recorder: MediaRecorder;
    try {
      recorder = new Recorder(stream, {
        ...(this.#options.mimeType ? { mimeType: this.#options.mimeType } : {}),
        audioBitsPerSecond: this.#options.audioBitsPerSecond
      });
      recorder.start(TIMESLICE_MS);
    } catch {
      return false;
    }
    const index = this.#nextIndex++;
    this.#partsThisStart += 1;
    let handOver: () => void = () => undefined;
    const part: Part = {
      recorder,
      index,
      chunks: [],
      startedAtMs: this.recordedMs(),
      capturedAt: this.#env.wallNow(),
      handedOver: new Promise<void>((resolve) => {
        handOver = resolve;
      })
    };
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) part.chunks.push(event.data);
    };
    recorder.onerror = () => {
      if (this.#part === part) void this.stop("error");
    };
    const previous = this.#handovers;
    this.#pendingHandovers += 1;
    recorder.onstop = () => {
      const durationMs = Math.max(0, this.recordedMs() - part.startedAtMs);
      const file = this.#partFile(part, durationMs);
      // Parts arrive in recording order, whichever file is built first.
      void Promise.all([previous, file]).then(([, built]) => {
        this.#pendingHandovers -= 1;
        if (built && !this.#disposed && this.#session) {
          this.#callbacks.onPart({
            file: built,
            sessionId: this.#session.sessionId,
            index: part.index,
            durationMs
          });
        }
        handOver();
      });
    };
    this.#handovers = part.handedOver;
    this.#part = part;
    return true;
  }

  async #partFile(part: Part, durationMs: number): Promise<File | null> {
    const [first, ...rest] = part.chunks;
    if (!first) return null;
    const type = part.recorder.mimeType || first.type || this.#options.mimeType || "audio/webm";
    const head = await withRecordedDuration(first, durationMs, type);
    const blob = new Blob([head, ...rest], { type });
    const name = partFileName(this.#session?.sessionId ?? "", part.index, part.capturedAt, type);
    return new File([blob], name, { type });
  }

  #stopPart(part: Part) {
    try {
      if (part.recorder.state !== "inactive") part.recorder.stop();
      else part.recorder.onstop?.(new Event("stop"));
    } catch {
      part.recorder.onstop?.(new Event("stop"));
    }
  }

  /** The next part starts on the live stream; the running one stops a moment later. */
  #rotate(): boolean {
    const previous = this.#part;
    if (!previous) return false;
    if (!this.#startPart()) {
      this.#part = previous;
      return false;
    }
    this.#callbacks.onRotate?.();
    setTimeout(() => this.#stopPart(previous), ROTATION_OVERLAP_MS);
    return true;
  }

  #limits(): RecorderLimits | null {
    return this.#session?.limits() ?? null;
  }

  #timeLeftMs(): number {
    const limits = this.#limits();
    if (!limits) return Infinity;
    return recordingTimeLeftMs(
      limits.maxRecordingMs,
      limits.partsBefore + this.#partsThisStart,
      limits.recordedBeforeMs + this.recordedMs()
    );
  }

  #minutesLeft(): number | null {
    const left = this.#timeLeftMs();
    if (!Number.isFinite(left)) return null;
    const minutes = Math.max(0, Math.ceil(left / 60_000));
    return minutes <= 10 ? minutes : null;
  }

  #onTick = () => {
    if (this.#snapshot.phase !== "recording") return;
    if (this.#timeLeftMs() <= 0) {
      void this.stop("length");
      return;
    }
    const limits = this.#limits();
    const part = this.#part;
    if (limits?.partMs && part && this.recordedMs() - part.startedAtMs >= limits.partMs) {
      // The running part and those still being handed over take slots too.
      const free = limits.filesLeft - this.#pendingHandovers;
      if (free < 1 || !this.#rotate()) {
        void this.stop("files");
        return;
      }
    }
    const minutesLeft = this.#minutesLeft();
    if (minutesLeft !== this.#snapshot.minutesLeft) this.#set({ ...this.#snapshot, minutesLeft });
  };

  #onTrackEnded = () => {
    void this.stop("device_lost");
  };

  #holdWakeLock() {
    // A phone screen that locks can stop the page's capture.
    void this.#env.wakeLock
      ?.request("screen")
      .then((lock) => {
        if (this.#snapshot.phase === "recording" || this.#snapshot.phase === "paused") {
          this.#wakeLock = lock;
        } else {
          void lock.release().catch(() => undefined);
        }
      })
      .catch(() => undefined);
  }

  #release() {
    clearInterval(this.#tick);
    const stream = this.#stream;
    this.#stream = null;
    if (stream) {
      for (const track of stream.getTracks()) {
        track.removeEventListener("ended", this.#onTrackEnded);
        track.stop();
      }
    }
    const context = this.#context;
    this.#context = null;
    void context?.close().catch(() => undefined);
    const lock = this.#wakeLock;
    this.#wakeLock = null;
    void lock?.release().catch(() => undefined);
  }

  #set(next: RecorderSnapshot) {
    this.#snapshot = next;
    for (const listener of this.#listeners) listener();
  }
}
