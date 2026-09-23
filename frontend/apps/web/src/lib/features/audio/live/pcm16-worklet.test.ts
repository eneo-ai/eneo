import { describe, expect, it } from "vitest";

import {
  createPcm16FrameWriter,
  createPcm16Processor,
  FRAME_SAMPLES,
  PCM16_FLUSH,
  PCM16_FLUSHED
} from "./pcm16-worklet.js";

// Feeds audio the way the worklet receives it, in render quanta of 128 samples.
function renderQuanta(
  inputRate: number,
  seconds: number,
  value: number,
  take: (block: Float32Array) => void
) {
  const total = Math.round(inputRate * seconds);
  for (let start = 0; start < total; start += 128) {
    take(new Float32Array(Math.min(128, total - start)).fill(value));
  }
}

function writeFrames(inputRate: number, seconds: number, value: number): ArrayBuffer[] {
  const frames: ArrayBuffer[] = [];
  const writer = createPcm16FrameWriter(inputRate, (frame) => frames.push(frame));
  renderQuanta(inputRate, seconds, value, (block) => writer.write(block));
  return frames;
}

function pcm16Samples(frame: ArrayBuffer): number[] {
  const view = new DataView(frame);
  return Array.from({ length: frame.byteLength / 2 }, (_, index) => view.getInt16(index * 2, true));
}

describe("createPcm16FrameWriter", () => {
  it.each([48_000, 44_100, 16_000])(
    "turns one second at %i Hz into ten 100 ms frames of 16 kHz PCM16",
    (inputRate) => {
      const frames = writeFrames(inputRate, 1, 0.5);

      expect(frames).toHaveLength(10);
      for (const frame of frames) {
        expect(frame.byteLength).toBe(FRAME_SAMPLES * 2);
        expect(new Set(pcm16Samples(frame))).toEqual(new Set([16384]));
      }
    }
  );

  it("clamps input beyond full scale", () => {
    const [loud] = writeFrames(48_000, 0.1, 1.5);
    const [loudNegative] = writeFrames(48_000, 0.1, -1.5);

    expect(new Set(pcm16Samples(loud))).toEqual(new Set([32767]));
    expect(new Set(pcm16Samples(loudNegative))).toEqual(new Set([-32768]));
  });
});

describe("createPcm16Processor", () => {
  it.each([48_000, 44_100])(
    "gives 150 ms of frames for 150 ms of audio at %i Hz once asked to flush",
    (inputRate) => {
      const posted: unknown[] = [];
      const port: Parameters<typeof createPcm16Processor>[1] = {
        postMessage: (message) => posted.push(message),
        onmessage: null
      };
      const process = createPcm16Processor(inputRate, port);

      renderQuanta(inputRate, 0.15, 0.5, (block) => process([[block]]));
      expect(posted).toHaveLength(1);
      port.onmessage?.({ data: PCM16_FLUSH });

      const frames = posted.filter((message) => message instanceof ArrayBuffer);
      const samples = frames.reduce((count, frame) => count + frame.byteLength / 2, 0);
      expect(samples).toBe(2_400);
      expect(posted.at(-1)).toBe(PCM16_FLUSHED);

      port.onmessage?.({ data: PCM16_FLUSH });
      expect(posted.slice(-2)).toEqual([PCM16_FLUSHED, PCM16_FLUSHED]);
    }
  );
});
