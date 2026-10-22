import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AudioRecorder,
  ROTATION_OVERLAP_MS,
  type RecordedPart,
  type RecorderLimits
} from "./recorder";

/** MediaRecorder as the recorder uses it: chunks come when the test says so. */
class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  state: RecordingState = "inactive";
  mimeType = "audio/ogg";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(
    readonly stream: unknown,
    readonly options: MediaRecorderOptions
  ) {
    FakeMediaRecorder.instances.push(this);
  }

  start() {
    this.state = "recording";
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  stop() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/ogg" }) });
    this.state = "inactive";
    queueMicrotask(() => this.onstop?.(new Event("stop")));
  }
}

function fakeStream() {
  const track = Object.assign(new EventTarget(), { stop: vi.fn() });
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  return { stream: stream as unknown as MediaStream, track };
}

function setup(getUserMedia: () => Promise<MediaStream>) {
  let now = 0;
  const parts: RecordedPart[] = [];
  const recorder = new AudioRecorder(
    { mimeType: "audio/ogg;codecs=opus", audioBitsPerSecond: 24_000 },
    { onPart: (part) => parts.push(part) },
    {
      mediaDevices: { getUserMedia },
      MediaRecorder: FakeMediaRecorder as unknown as typeof MediaRecorder,
      AudioContext: undefined,
      isSecureContext: true,
      wakeLock: undefined,
      now: () => now,
      wallNow: () => Date.UTC(2026, 9, 22, 8, 0, 0) + now
    }
  );
  return {
    recorder,
    parts,
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
    ...overrides
  });

beforeEach(() => {
  FakeMediaRecorder.instances = [];
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
        wallNow: () => 0
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
});
