import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JournalPart } from "./recording-keeper";
import {
  AudioRecorder,
  MAX_PARTS_AWAITING_UPLOAD,
  ROTATION_OVERLAP_MS,
  SILENCE_HINT_MS,
  STALL_GRACE_MS,
  STALL_MS,
  type RecordedPart,
  type RecorderLimits
} from "./recorder";

/**
 * MediaRecorder as the recorder uses it: a chunk every timeslice while it
 * records (unless the test makes it `frozen`), on `requestData` and on stop.
 */
class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  state: RecordingState = "inactive";
  mimeType = "audio/ogg";
  frozen = false;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: (() => void) | null = null;
  #timer: ReturnType<typeof setInterval> | undefined;

  constructor(
    readonly stream: unknown,
    readonly options: MediaRecorderOptions
  ) {
    FakeMediaRecorder.instances.push(this);
  }

  #emit() {
    if (!this.frozen) this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/ogg" }) });
  }

  start(timeslice?: number) {
    this.state = "recording";
    this.#timer = setInterval(() => {
      if (this.state === "recording") this.#emit();
    }, timeslice ?? 1_000);
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  requestData() {
    this.#emit();
  }
  stop() {
    clearInterval(this.#timer);
    this.#emit();
    this.state = "inactive";
    queueMicrotask(() => this.onstop?.(new Event("stop")));
  }
}

/** The audio graph's analyser: the level the test sets is what it measures. */
class FakeAudioContext {
  static level = 0;
  state = "running";
  createMediaStreamSource() {
    return { connect: vi.fn(), disconnect: vi.fn() };
  }
  createAnalyser() {
    return {
      fftSize: 4,
      getFloatTimeDomainData: (buffer: Float32Array) => buffer.fill(FakeAudioContext.level * 0.15)
    };
  }
  close() {
    return Promise.resolve();
  }
}

function fakeStream() {
  const track = Object.assign(new EventTarget(), { stop: vi.fn() });
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  return { stream: stream as unknown as MediaStream, track };
}

function setup(
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>,
  { meter = false, journal }: { meter?: boolean; journal?: JournalSpy } = {}
) {
  let now = 0;
  let hidden = false;
  const parts: RecordedPart[] = [];
  const recorder = new AudioRecorder(
    { mimeType: "audio/ogg;codecs=opus", audioBitsPerSecond: 24_000 },
    { onPart: (part) => parts.push(part), ...(journal ? { journal } : {}) },
    {
      mediaDevices: { getUserMedia },
      MediaRecorder: FakeMediaRecorder as unknown as typeof MediaRecorder,
      AudioContext: meter ? (FakeAudioContext as unknown as typeof AudioContext) : undefined,
      isSecureContext: true,
      wakeLock: undefined,
      now: () => now,
      wallNow: () => Date.UTC(2026, 9, 22, 8, 0, 0) + now,
      isHidden: () => hidden
    }
  );
  return {
    recorder,
    parts,
    hide: (value: boolean) => {
      hidden = value;
    },
    /** `ms` pass on the clock; timers fire for `timerMs` of them (a hidden tab fires late). */
    advance: async (ms: number, timerMs = ms) => {
      now += ms;
      await vi.advanceTimersByTimeAsync(timerMs);
    }
  };
}

const limits =
  (overrides: Partial<RecorderLimits> = {}) =>
  () => ({
    partMs: null,
    maxRecordingMs: null,
    recordedBeforeMs: 0,
    partsBefore: 0,
    filesLeft: 5,
    awaitingUpload: 0,
    ...overrides
  });

type JournalSpy = {
  begin: ReturnType<typeof vi.fn<(part: JournalPart) => void>>;
  append: ReturnType<typeof vi.fn<(part: JournalPart, chunk: Blob, recordedMs: number) => void>>;
  leave: ReturnType<typeof vi.fn<(part: JournalPart) => void>>;
  discard: ReturnType<typeof vi.fn<(part: JournalPart) => void>>;
};

const journalSpy = (): JournalSpy => ({
  begin: vi.fn(),
  append: vi.fn(),
  leave: vi.fn(),
  discard: vi.fn()
});

beforeEach(() => {
  FakeMediaRecorder.instances = [];
  FakeAudioContext.level = 0;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
});
afterEach(() => vi.useRealTimers());

describe("AudioRecorder", () => {
  it("says why the microphone could not be used", async () => {
    for (const [name, problem] of [
      ["NotAllowedError", "permission_denied"],
      ["NotFoundError", "no_microphone"],
      ["NotReadableError", "microphone_busy"],
      ["TypeError", "microphone_failed"]
    ] as const) {
      const { recorder } = setup(() => Promise.reject(new DOMException("no", name)));
      await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
      expect(recorder.getSnapshot(), name).toMatchObject({ phase: "idle", problem });
    }
  });

  it("explains an insecure page or a browser without recording", async () => {
    const { recorder } = setup(() => Promise.reject(new Error("unused")));
    const insecure = new AudioRecorder(
      { audioBitsPerSecond: 24_000 },
      { onPart: () => undefined },
      {
        mediaDevices: undefined,
        MediaRecorder: undefined,
        AudioContext: undefined,
        isSecureContext: false,
        wakeLock: undefined,
        now: () => 0,
        wallNow: () => 0,
        isHidden: () => false
      }
    );
    await insecure.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
    expect(insecure.getSnapshot().problem).toBe("insecure");
    expect(recorder.getSnapshot().problem).toBeNull();
  });

  it("records, leaves pauses out of the clock and hands the part over on stop", async () => {
    const { stream, track } = fakeStream();
    const { recorder, parts, advance } = setup(() => Promise.resolve(stream));
    await recorder.start({ sessionId: "abc", firstIndex: 2, limits: limits() });
    expect(recorder.getSnapshot().phase).toBe("recording");
    await advance(10_000);
    recorder.pause();
    expect(recorder.getSnapshot()).toMatchObject({ phase: "paused", recordedMs: 10_000 });
    await advance(5_000);
    recorder.resume();
    await advance(2_000);
    await recorder.stop();

    expect(recorder.getSnapshot()).toMatchObject({ phase: "idle", ended: "manual" });
    expect(parts).toHaveLength(1);
    expect(parts[0]).toMatchObject({ sessionId: "abc", index: 2, durationMs: 12_000 });
    expect(parts[0]!.file.name).toBe("recording-abc-seg02-2026-10-22T08-00-00-000Z.ogg");
    expect(track.stop).toHaveBeenCalled();
  });

  it("goes on in a new part at the part length, overlapping the last, in order", async () => {
    const { stream } = fakeStream();
    const { recorder, parts, advance } = setup(() => Promise.resolve(stream));
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits({ partMs: 60_000 }) });
    await advance(60_000, 500);
    expect(FakeMediaRecorder.instances).toHaveLength(2);
    expect(FakeMediaRecorder.instances[0]!.state).toBe("recording");
    await advance(ROTATION_OVERLAP_MS);
    expect(FakeMediaRecorder.instances[0]!.state).toBe("inactive");
    await advance(30_000);
    await recorder.stop();
    expect(parts.map((part) => part.index)).toEqual([0, 1]);
  });

  it("stops at the last file slot and at the longest recording", async () => {
    const { stream } = fakeStream();
    const slots = setup(() => Promise.resolve(stream));
    await slots.recorder.start({
      sessionId: "abc",
      firstIndex: 0,
      limits: limits({ partMs: 60_000, filesLeft: 1 })
    });
    await slots.advance(60_500);
    await vi.waitFor(() => expect(slots.recorder.getSnapshot().ended).toBe("files"));

    const length = setup(() => Promise.resolve(fakeStream().stream));
    await length.recorder.start({
      sessionId: "abc",
      firstIndex: 0,
      limits: limits({ maxRecordingMs: 60_000 })
    });
    await length.advance(50_000);
    expect(length.recorder.getSnapshot().minutesLeft).toBe(1);
    await length.advance(10_000);
    await vi.waitFor(() => expect(length.recorder.getSnapshot().ended).toBe("length"));
    expect(length.parts).toHaveLength(1);
  });

  it("keeps what was recorded when the microphone goes away", async () => {
    const { stream, track } = fakeStream();
    const { recorder, parts, advance } = setup(() => Promise.resolve(stream));
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
    await advance(3_000);
    track.dispatchEvent(new Event("ended"));
    await vi.waitFor(() => expect(recorder.getSnapshot().ended).toBe("device_lost"));
    expect(parts).toHaveLength(1);
  });

  it("journals each chunk of a part, and leaves the part the page goes away from", async () => {
    const journal = journalSpy();
    const { recorder, advance } = setup(() => Promise.resolve(fakeStream().stream), { journal });
    await recorder.start({ sessionId: "abc", firstIndex: 3, limits: limits() });
    await advance(2_000);
    const capturedAt = Date.UTC(2026, 9, 22, 8, 0, 0);
    const part = { sessionId: "abc", index: 3, mimeType: "audio/ogg", capturedAt };
    expect(journal.begin).toHaveBeenCalledWith(part);
    expect(journal.append).toHaveBeenCalledTimes(2);
    expect(journal.append.mock.calls[1]![2]).toBe(2_000);
    recorder.dispose();
    expect(journal.leave).toHaveBeenCalledWith(part);
  });

  it("stops when no audio arrives any more, after asking the recorder for it", async () => {
    const { recorder, advance } = setup(() => Promise.resolve(fakeStream().stream));
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
    await advance(2_000);
    FakeMediaRecorder.instances[0]!.frozen = true;
    await advance(STALL_MS + 500);
    // Asked for its data first: the person hears the recorder is trying.
    expect(recorder.getSnapshot()).toMatchObject({ phase: "recording", micHint: "reconnecting" });
    await advance(STALL_GRACE_MS);
    await vi.waitFor(() => expect(recorder.getSnapshot().ended).toBe("stall"));
  });

  it("holds nothing against a hidden page, nor its time against a chunk from before", async () => {
    const { recorder, advance, hide } = setup(() => Promise.resolve(fakeStream().stream));
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
    await advance(2_000);
    FakeMediaRecorder.instances[0]!.frozen = true;
    hide(true);
    await advance(60_000);
    expect(recorder.getSnapshot()).toMatchObject({ phase: "recording", micHint: null });
    hide(false);
    FakeMediaRecorder.instances[0]!.frozen = false;
    await advance(1_000);
    expect(recorder.getSnapshot()).toMatchObject({ phase: "recording", micHint: null });
  });

  it("says when the system muted the microphone and when it has been quiet", async () => {
    const { stream, track } = fakeStream();
    const { recorder, advance } = setup(() => Promise.resolve(stream), { meter: true });
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
    FakeAudioContext.level = 0.5;
    await advance(1_000);
    expect(recorder.level()).toBeCloseTo(0.5);
    expect(recorder.getSnapshot().micHint).toBeNull();

    FakeAudioContext.level = 0;
    await advance(SILENCE_HINT_MS + 1_000);
    expect(recorder.getSnapshot().micHint).toBe("silent");
    track.dispatchEvent(new Event("mute"));
    expect(recorder.getSnapshot().micHint).toBe("muted");
    track.dispatchEvent(new Event("unmute"));
    FakeAudioContext.level = 0.4;
    await advance(500);
    expect(recorder.getSnapshot().micHint).toBeNull();

    recorder.pause();
    expect(recorder.level()).toBe(0);
    expect(recorder.getSnapshot().micHint).toBeNull();
  });

  it("asks again with looser settings when no microphone meets the preferred ones", async () => {
    const { stream, track } = fakeStream();
    const applyConstraints = vi.fn(() =>
      Promise.reject(new DOMException("no", "OverconstrainedError"))
    );
    Object.assign(track, { applyConstraints });
    const getUserMedia = vi
      .fn<(constraints: MediaStreamConstraints) => Promise<MediaStream>>()
      .mockRejectedValueOnce(new DOMException("no", "OverconstrainedError"))
      .mockResolvedValueOnce(stream);
    const { recorder } = setup(getUserMedia);
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });

    expect(recorder.getSnapshot().phase).toBe("recording");
    expect(getUserMedia.mock.calls.map(([constraints]) => constraints.audio)).toEqual([
      { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      true
    ]);
    // The preferred settings are applied where the microphone can; here it records as it is.
    expect(applyConstraints).toHaveBeenCalledWith(expect.objectContaining({ channelCount: 1 }));
    const report = recorder.diagnostics();
    expect(report.microphone.constraints).toBe("relaxed");
    expect(report.events.map((entry) => entry.event)).toEqual(
      expect.arrayContaining([
        "microphone_refused",
        "microphone_retry_relaxed",
        "constraints_not_applied",
        "microphone_open"
      ])
    );
  });

  it("does not ask again after a refusal that is not about the settings", async () => {
    const getUserMedia = vi.fn(() => Promise.reject(new DOMException("no", "NotAllowedError")));
    const { recorder } = setup(getUserMedia);
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits() });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(recorder.getSnapshot().problem).toBe("permission_denied");
  });

  it("tells the part's size as it grows and from zero in a new part", async () => {
    const { stream } = fakeStream();
    const { recorder, advance } = setup(() => Promise.resolve(stream));
    await recorder.start({ sessionId: "abc", firstIndex: 0, limits: limits({ partMs: 60_000 }) });
    await advance(3_000);
    // Each fake chunk is the five bytes of "audio".
    expect(recorder.getSnapshot().partBytes).toBe(15);
    await advance(57_000, 500);
    expect(recorder.getSnapshot().partBytes).toBe(0);
    await advance(2_000);
    expect(recorder.getSnapshot().partBytes).toBe(10);
  });

  it("reports its state and recent events without naming the device", async () => {
    const { stream, track } = fakeStream();
    Object.assign(track, {
      getSettings: () => ({
        deviceId: "device-secret",
        groupId: "group-secret",
        sampleRate: 48_000,
        channelCount: 1,
        echoCancellation: true
      })
    });
    const { recorder, advance } = setup(() => Promise.resolve(stream));
    await recorder.start({ sessionId: "session-secret", firstIndex: 0, limits: limits() });
    await advance(2_000);
    const report = recorder.diagnostics();
    expect(report).toMatchObject({
      phase: "recording",
      format: {
        requested: "audio/ogg;codecs=opus",
        recorder: "audio/ogg",
        audioBitsPerSecond: 24_000
      },
      microphone: {
        constraints: "preferred",
        settings: { sampleRate: 48_000, channelCount: 1, echoCancellation: true }
      },
      recording: {
        recordedMs: 2_000,
        part: { index: 0, chunks: 2, bytes: 10 },
        firstChunkAfterMs: expect.any(Number)
      }
    });
    expect(report.events.map((entry) => entry.event)).toEqual([
      "start",
      "microphone_open",
      "part_started",
      "first_chunk"
    ]);
    const text = JSON.stringify(report);
    expect(text).not.toMatch(/secret/);
  });

  it("stops rather than pile up parts waiting for their upload", async () => {
    const { recorder, advance, parts } = setup(() => Promise.resolve(fakeStream().stream));
    await recorder.start({
      sessionId: "abc",
      firstIndex: 0,
      limits: limits({ partMs: 60_000, awaitingUpload: MAX_PARTS_AWAITING_UPLOAD - 1 })
    });
    await advance(60_500);
    await vi.waitFor(() => expect(recorder.getSnapshot().ended).toBe("backlog"));
    expect(parts).toHaveLength(1);
  });
});
