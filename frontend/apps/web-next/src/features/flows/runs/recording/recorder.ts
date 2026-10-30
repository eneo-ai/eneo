import { partFileName, recordingTimeLeftMs, type RecordingOptions } from "./recording-format";
import type { RecorderAudioGraph } from "./live-transcript";
import type { JournalPart, RecorderJournal } from "./recording-keeper";
import {
  microphoneSettings,
  RecorderEventLog,
  type MicrophoneSettings,
  type RecorderDiagnostics
} from "./recorder-diagnostics";
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
 * A microphone that cannot meet the preferred settings (one channel, echo
 * cancellation, noise suppression) is asked for again with none, and the
 * settings are then applied where it can. What happened is kept as recent
 * events for the recording's diagnostics (`diagnostics()`).
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

/**
 * Why the last recording stopped: the person, the step's longest recording
 * or last file slot, parts waiting for their upload, the microphone going
 * away, no audio arriving any more, or a recorder error.
 */
export type RecordingEnd =
  "manual" | "length" | "files" | "backlog" | "device_lost" | "stall" | "error";

/**
 * Why the microphone may not be heard, while recording: the system muted
 * it, no audio arrived for a while (the recorder is asked for it), or it
 * has been quiet for a while.
 */
export type MicrophoneHint = "muted" | "reconnecting" | "silent";

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
  /** Why the microphone may not be heard; null while it is, or while not recording. */
  micHint: MicrophoneHint | null;
  /** Bytes of the part being recorded so far, as its chunks arrive. */
  partBytes: number;
};

export type RecordedPart = {
  file: File;
  sessionId: string;
  index: number;
  durationMs: number;
  /** Wall-clock time at which the part started, which its file name carries. */
  capturedAt: number;
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
  /** The step's recorded parts handed over and not uploaded yet. */
  awaitingUpload: number;
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
  /**
   * Where each part's chunks are written as they come, so a closed tab or a
   * crash keeps what was recorded. A handed-over part's journal is ended by
   * whoever stores the part; one the page leaves mid-recording stays.
   */
  journal?: RecorderJournal;
};

type RecorderEnvironment = {
  mediaDevices:
    | (Pick<MediaDevices, "getUserMedia"> & Partial<Pick<MediaDevices, "enumerateDevices">>)
    | undefined;
  MediaRecorder: typeof MediaRecorder | undefined;
  AudioContext: typeof AudioContext | undefined;
  isSecureContext: boolean;
  wakeLock: { request(type: "screen"): Promise<{ release(): Promise<void> }> } | undefined;
  /** A monotonic clock: a system clock set during a meeting must not change the recording. */
  now: () => number;
  wallNow: () => number;
  /** Whether the page is hidden, when timers and the encoder run late. */
  isHidden: () => boolean;
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
    wallNow: () => Date.now(),
    isHidden: () => typeof document !== "undefined" && document.visibilityState === "hidden"
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
/**
 * More parts than this waiting for their upload stop the recording rather
 * than pile up audio the server has not received (the running part counts).
 */
export const MAX_PARTS_AWAITING_UPLOAD = 3;
/**
 * No chunk for this long means capture has stopped (a frozen tab, a lost
 * device): before the first chunk an encoder may take long to start, after
 * it a second is the norm. The recorder is then asked for its data and gets
 * a grace period before the recording stops.
 */
export const STALL_BEFORE_FIRST_CHUNK_MS = 10_000;
export const STALL_MS = 5_000;
export const STALL_GRACE_MS = 2_000;
/** A level above this is someone speaking; quiet for longer than the hint delay is a hint. */
const AUDIBLE_LEVEL = 0.035;
export const SILENCE_HINT_MS = 6_000;

/** What the recorder asks of the microphone first. */
const PREFERRED_AUDIO: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1
};

/** Refusals that may be about the settings asked for rather than the microphone itself. */
const RELAXABLE = new Set(["NotFoundError", "OverconstrainedError"]);

function errorName(error: unknown): string {
  return error instanceof DOMException || error instanceof Error ? error.name : "unknown";
}

function problemOf(error: unknown): RecorderProblem {
  const name = errorName(error);
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
  /** What the journal knows the part by. */
  journal: JournalPart;
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
  minutesLeft: null,
  micHint: null,
  partBytes: 0
};

export class AudioRecorder {
  #snapshot: RecorderSnapshot = IDLE;
  #listeners = new Set<() => void>();
  #env: RecorderEnvironment;
  #options: RecordingOptions;
  #callbacks: RecorderCallbacks;

  #stream: MediaStream | null = null;
  #context: AudioContext | null = null;
  #analyser: AnalyserNode | null = null;
  #levels: Float32Array<ArrayBuffer> | null = null;
  /** Monotonic time of the running part's last chunk, for the stall watch. */
  #lastChunkAt = 0;
  #firstChunkSeen = false;
  /** When the recorder was asked for its data because none came; null otherwise. */
  #rescueAt: number | null = null;
  #hiddenSince: number | null = null;
  #lastAudibleAt = 0;
  #muted = false;
  #wakeLock: { release(): Promise<void> } | null = null;
  #part: Part | null = null;
  #handovers: Promise<void> = Promise.resolve();
  #pendingHandovers = 0;
  /** Parts started and not handed over yet, whose journals the page would leave. */
  #unhanded = new Set<Part>();
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

  // What the diagnostics tell: nothing that names the person or the device.
  #log: RecorderEventLog;
  #constraints: "preferred" | "relaxed" | null = null;
  #settings: MicrophoneSettings | null = null;
  #inputs: number | null = null;
  #partChunks = 0;
  #partBytes = 0;
  #emptyChunks = 0;
  /** Monotonic time the running start began recording, for the first chunk's delay. */
  #recordingSince = 0;
  #firstChunkAfterMs: number | null = null;

  constructor(
    options: RecordingOptions,
    callbacks: RecorderCallbacks = { onPart: () => undefined },
    environment: RecorderEnvironment = browserEnvironment()
  ) {
    this.#options = options;
    this.#callbacks = callbacks;
    this.#env = environment;
    this.#log = new RecorderEventLog(environment.now);
  }

  /** Who hears of parts, the audio graph and pauses from now on. */
  setCallbacks(callbacks: RecorderCallbacks): void {
    this.#callbacks = callbacks;
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
    this.#emptyChunks = 0;
    this.#firstChunkAfterMs = null;
    this.#log.add("start", `part ${options.firstIndex + 1}`);
    this.#set({ ...IDLE, phase: "starting" });

    let stream: MediaStream;
    try {
      stream = await this.#openMicrophone(attempt);
    } catch (error) {
      if (attempt === this.#attempt) this.#set({ ...IDLE, problem: problemOf(error) });
      return;
    }
    if (attempt !== this.#attempt || this.#disposed) {
      for (const track of stream.getTracks()) track.stop();
      return;
    }
    this.#stream = stream;
    this.#muted = false;
    this.#settings = microphoneSettings(stream.getAudioTracks()[0]?.getSettings?.());
    this.#log.add("microphone_open", this.#constraints ?? undefined);
    for (const track of stream.getAudioTracks()) {
      track.addEventListener("ended", this.#onTrackEnded);
      track.addEventListener("mute", this.#onMute);
      track.addEventListener("unmute", this.#onUnmute);
    }

    await this.#openGraph(stream);
    if (attempt !== this.#attempt || this.#disposed) {
      this.#callbacks.onAudioGraph?.(null);
      this.#release();
      return;
    }

    this.#clockStartedAt = this.#env.now();
    this.#pausedAt = null;
    this.#pausedTotal = 0;
    this.#firstChunkSeen = false;
    this.#recordingSince = this.#env.now();
    if (!this.#startPart()) {
      this.#log.add("recorder_failed");
      this.#callbacks.onAudioGraph?.(null);
      this.#release();
      this.#set({ ...IDLE, problem: "microphone_failed" });
      return;
    }
    this.#holdWakeLock();
    // The watch starts once the recorder runs: the permission prompt is not a stall.
    this.#lastChunkAt = this.#env.now();
    this.#lastAudibleAt = this.#lastChunkAt;
    this.#rescueAt = null;
    this.#hiddenSince = null;
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
    this.#log.add("paused");
    this.#set({
      ...this.#snapshot,
      phase: "paused",
      recordedMs: this.recordedMs(),
      clockStartedAt: null,
      micHint: null
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
    this.#log.add("resumed");
    // No chunk came while paused, and nobody spoke: both watches start again.
    this.#lastChunkAt = this.#env.now();
    this.#lastAudibleAt = this.#lastChunkAt;
    this.#rescueAt = null;
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
      this.#log.add("start_cancelled");
      this.#attempt += 1;
      this.#set({ ...IDLE });
      return Promise.resolve();
    }
    if (phase !== "recording" && phase !== "paused") return this.#handovers;
    const recorded = this.recordedMs();
    this.#log.add("stopped", reason);
    // The clock stops here: the last part's length is what was recorded until now.
    this.#pausedAt ??= this.#env.now();
    clearInterval(this.#tick);
    this.#set({
      ...this.#snapshot,
      phase: "stopping",
      recordedMs: recorded,
      clockStartedAt: null,
      micHint: null
    });
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

  /**
   * Lets go of the microphone at once; nothing more is handed over. What the
   * journal holds of the parts not handed over stays, to be rebuilt.
   */
  dispose(): void {
    this.#disposed = true;
    this.#attempt += 1;
    clearInterval(this.#tick);
    for (const part of this.#unhanded) this.#callbacks.journal?.leave(part.journal);
    this.#unhanded.clear();
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

  /**
   * The microphone with the preferred settings; where the browser finds no
   * microphone that meets them, again with none (any microphone, as it
   * records), and the preferred settings are then applied where it can.
   */
  async #openMicrophone(attempt: number): Promise<MediaStream> {
    const devices = this.#env.mediaDevices!;
    this.#constraints = null;
    this.#inputs = null;
    try {
      const stream = await devices.getUserMedia({ audio: PREFERRED_AUDIO });
      this.#constraints = "preferred";
      return stream;
    } catch (error) {
      this.#log.add("microphone_refused", errorName(error));
      await this.#countInputs();
      if (!RELAXABLE.has(errorName(error)) || attempt !== this.#attempt) throw error;
    }
    this.#log.add("microphone_retry_relaxed");
    let stream: MediaStream;
    try {
      stream = await devices.getUserMedia({ audio: true });
    } catch (error) {
      this.#log.add("microphone_refused", errorName(error));
      throw error;
    }
    this.#constraints = "relaxed";
    try {
      await stream.getAudioTracks()[0]?.applyConstraints?.(PREFERRED_AUDIO);
    } catch (error) {
      // The microphone records as it is.
      this.#log.add("constraints_not_applied", errorName(error));
    }
    return stream;
  }

  /** How many microphones the browser lists, without their names. */
  async #countInputs() {
    try {
      const devices = (await this.#env.mediaDevices?.enumerateDevices?.()) ?? null;
      if (!devices) return;
      this.#inputs = devices.filter((device) => device.kind === "audioinput").length;
      this.#log.add("microphones_listed", String(this.#inputs));
    } catch {
      // Nothing to count.
    }
  }

  /** The recorder's state, settings, counters and recent events, for the diagnostics. */
  diagnostics(): RecorderDiagnostics {
    const { phase, problem, ended, micHint } = this.#snapshot;
    const part = this.#part;
    const running = phase === "recording" || phase === "paused";
    const now = this.#env.now();
    return {
      phase,
      problem,
      ended,
      support: {
        secureContext: this.#env.isSecureContext,
        mediaRecorder: Boolean(this.#env.MediaRecorder),
        audioContext: Boolean(this.#env.AudioContext)
      },
      format: {
        requested: this.#options.mimeType ?? null,
        recorder: part?.recorder.mimeType || null,
        audioBitsPerSecond: this.#options.audioBitsPerSecond
      },
      microphone: {
        constraints: this.#constraints,
        settings: this.#settings,
        inputs: this.#inputs,
        muted: this.#muted
      },
      meter: this.#context
        ? { state: this.#context.state, sampleRate: this.#context.sampleRate }
        : null,
      recording: {
        recordedMs: Math.round(running ? this.recordedMs() : this.#snapshot.recordedMs),
        partsThisStart: this.#partsThisStart,
        part: part ? { index: part.index, chunks: this.#partChunks, bytes: this.#partBytes } : null,
        pendingParts: this.#pendingHandovers,
        emptyChunks: this.#emptyChunks,
        firstChunkAfterMs: this.#firstChunkAfterMs,
        lastChunkAgoMs: running ? Math.round(now - this.#lastChunkAt) : null,
        micHint
      },
      events: this.#log.list()
    };
  }

  /**
   * The microphone's audio graph: the level meter's analyser, and the live
   * text's tap when it listens. Without an audio graph the recording goes on
   * without either.
   */
  async #openGraph(stream: MediaStream) {
    const Context = this.#env.AudioContext;
    if (!Context) return;
    let graph: RecorderAudioGraph;
    try {
      const context = new Context();
      this.#context = context;
      graph = { context, source: context.createMediaStreamSource(stream) };
      // A context made outside a user gesture (an automatic restart) may start suspended.
      if (context.state === "suspended") void context.resume().catch(() => undefined);
    } catch (error) {
      this.#log.add("audio_graph_failed", errorName(error));
      return;
    }
    try {
      const analyser = graph.context.createAnalyser();
      graph.source.connect(analyser);
      this.#analyser = analyser;
      this.#levels = new Float32Array(analyser.fftSize);
    } catch {
      // No meter: the recording goes on.
    }
    const listener = this.#callbacks.onAudioGraph;
    if (!listener) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.resolve(listener(graph, abort.signal)).catch(() => undefined),
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, GRAPH_PREPARATION_MS);
        })
      ]);
    } finally {
      clearTimeout(timer);
      abort.abort();
    }
  }

  /** Whether the microphone's level can be measured while recording. */
  get hasMeter(): boolean {
    return this.#analyser !== null;
  }

  /**
   * The microphone's level now, 0 to 1 (speech is about 0.1 to 0.6); 0 while
   * nothing is measured, and null where there is no meter.
   */
  level(): number | null {
    const analyser = this.#analyser;
    const levels = this.#levels;
    if (!analyser || !levels) return null;
    if (this.#snapshot.phase !== "recording") return 0;
    try {
      analyser.getFloatTimeDomainData(levels);
    } catch {
      return null;
    }
    let sum = 0;
    for (const amplitude of levels) sum += amplitude * amplitude;
    return Math.min(1, Math.sqrt(sum / levels.length) / 0.15);
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
    } catch (error) {
      this.#log.add("part_not_started", errorName(error));
      return false;
    }
    const index = this.#nextIndex++;
    this.#partsThisStart += 1;
    this.#partChunks = 0;
    this.#partBytes = 0;
    this.#log.add("part_started", `part ${index + 1}, ${recorder.mimeType || "default type"}`);
    let handOver: () => void = () => undefined;
    const capturedAt = this.#env.wallNow();
    const journal = this.#callbacks.journal;
    const part: Part = {
      recorder,
      index,
      journal: {
        sessionId: this.#session?.sessionId ?? "",
        index,
        mimeType: recorder.mimeType || this.#options.mimeType || "audio/webm",
        capturedAt
      },
      chunks: [],
      startedAtMs: this.recordedMs(),
      capturedAt,
      handedOver: new Promise<void>((resolve) => {
        handOver = resolve;
      })
    };
    this.#unhanded.add(part);
    journal?.begin(part.journal);
    let emptyTold = false;
    recorder.ondataavailable = (event: BlobEvent) => {
      // An empty chunk is no sign of life: it must not quiet the stall watch.
      if (event.data.size === 0) {
        this.#emptyChunks += 1;
        if (!emptyTold) this.#log.add("chunk_empty", `part ${index + 1}`);
        emptyTold = true;
        return;
      }
      if (this.#part === part) {
        const now = this.#env.now();
        this.#lastChunkAt = now;
        if (this.#firstChunkAfterMs === null) {
          this.#firstChunkAfterMs = Math.round(now - this.#recordingSince);
          this.#log.add("first_chunk", `${this.#firstChunkAfterMs} ms`);
        }
        this.#firstChunkSeen = true;
        this.#rescueAt = null;
        this.#partChunks += 1;
        this.#partBytes += event.data.size;
        const { phase } = this.#snapshot;
        if (phase === "recording" || phase === "paused") {
          this.#set({ ...this.#snapshot, partBytes: this.#partBytes });
        }
      }
      part.chunks.push(event.data);
      journal?.append(part.journal, event.data, Math.max(0, this.recordedMs() - part.startedAtMs));
    };
    recorder.onerror = (event: Event) => {
      const error = (event as Event & { error?: unknown }).error;
      this.#log.add("recorder_error", `part ${index + 1}, ${errorName(error)}`);
      if (this.#part === part) void this.stop("error");
    };
    const previous = this.#handovers;
    this.#pendingHandovers += 1;
    recorder.onstop = () => {
      const durationMs = Math.max(0, this.recordedMs() - part.startedAtMs);
      const file = this.#partFile(part, durationMs);
      // Parts arrive in recording order, whichever file is built first.
      void Promise.all([previous, file.catch(() => null)]).then(([, built]) => {
        this.#pendingHandovers -= 1;
        if (!this.#disposed) {
          this.#unhanded.delete(part);
          if (built && this.#session) {
            this.#log.add(
              "part_handed_over",
              `part ${part.index + 1}, ${Math.round(durationMs)} ms, ${built.size} B`
            );
            this.#callbacks.onPart({
              file: built,
              sessionId: this.#session.sessionId,
              index: part.index,
              durationMs,
              capturedAt: part.capturedAt
            });
          } else {
            this.#log.add("part_empty", `part ${part.index + 1}`);
            journal?.discard(part.journal);
          }
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
    let head: Blob = first;
    try {
      head = await withRecordedDuration(first, durationMs, type);
    } catch {
      // The header stays as recorded: players then guess the length.
    }
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
    this.#set({ ...this.#snapshot, partBytes: 0 });
    // The new part's encoder starts again: it may take its time for the first chunk.
    this.#firstChunkSeen = false;
    this.#lastChunkAt = this.#env.now();
    this.#rescueAt = null;
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
      // The finishing part joins those waiting for their upload.
      if (limits.awaitingUpload + this.#pendingHandovers >= MAX_PARTS_AWAITING_UPLOAD) {
        void this.stop("backlog");
        return;
      }
      // The running part and those still being handed over take slots too.
      const free = limits.filesLeft - this.#pendingHandovers;
      if (free < 1 || !this.#rotate()) {
        void this.stop("files");
        return;
      }
    }
    if (this.#watchStall()) return;
    const minutesLeft = this.#minutesLeft();
    const micHint = this.#micHint();
    if (minutesLeft !== this.#snapshot.minutesLeft || micHint !== this.#snapshot.micHint) {
      this.#set({ ...this.#snapshot, minutesLeft, micHint });
    }
  };

  /**
   * Stops the recording when no audio arrives any more; true when it did.
   * A hidden page decides nothing (its timers and encoder run late), and the
   * time it was hidden is not held against a chunk from before.
   */
  #watchStall(): boolean {
    const now = this.#env.now();
    if (this.#env.isHidden()) {
      if (this.#hiddenSince === null) this.#log.add("page_hidden");
      this.#hiddenSince ??= now;
      this.#rescueAt = null;
      return false;
    }
    if (this.#hiddenSince !== null) {
      this.#log.add("page_visible");
      const hiddenFor = now - this.#hiddenSince;
      if (this.#lastChunkAt <= this.#hiddenSince) this.#lastChunkAt += hiddenFor;
      if (this.#lastAudibleAt <= this.#hiddenSince) this.#lastAudibleAt += hiddenFor;
      this.#hiddenSince = null;
    }
    const limit = this.#firstChunkSeen ? STALL_MS : STALL_BEFORE_FIRST_CHUNK_MS;
    if (now - this.#lastChunkAt <= limit) {
      this.#rescueAt = null;
      return false;
    }
    if (this.#rescueAt === null) {
      // Some encoders hold chunks back under load: a healthy one answers this at once.
      this.#rescueAt = now;
      this.#log.add("data_requested", `${Math.round(now - this.#lastChunkAt)} ms without audio`);
      try {
        this.#part?.recorder.requestData();
      } catch {
        // It answers with the stop instead.
      }
      return false;
    }
    if (now - this.#rescueAt < STALL_GRACE_MS) return false;
    this.#log.add("stalled");
    void this.stop("stall");
    return true;
  }

  #micHint(): MicrophoneHint | null {
    if (this.#muted) return "muted";
    if (this.#rescueAt !== null) return "reconnecting";
    const level = this.level();
    // A context that is not running measures nothing: that is not silence.
    if (level === null || this.#context?.state !== "running") return null;
    const now = this.#env.now();
    if (level > AUDIBLE_LEVEL) this.#lastAudibleAt = now;
    return now - this.#lastAudibleAt > SILENCE_HINT_MS ? "silent" : null;
  }

  #onTrackEnded = () => {
    this.#log.add("microphone_ended");
    void this.stop("device_lost");
  };

  // The system may mute the microphone for a moment (a headset switching
  // over): the recording goes on, and the person is told.
  #onMute = () => {
    this.#log.add("microphone_muted");
    this.#muted = true;
    if (this.#snapshot.phase === "recording") this.#set({ ...this.#snapshot, micHint: "muted" });
  };

  #onUnmute = () => {
    this.#log.add("microphone_unmuted");
    this.#muted = false;
    if (this.#snapshot.phase === "recording") this.#set({ ...this.#snapshot, micHint: null });
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
        track.removeEventListener("mute", this.#onMute);
        track.removeEventListener("unmute", this.#onUnmute);
        track.stop();
      }
    }
    this.#analyser = null;
    this.#levels = null;
    this.#muted = false;
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
