import { describe, expect, it } from "vitest";

import { createPcm16FrameWriter, FRAME_SAMPLES } from "./pcm16-worklet.js";

// Feeds audio the way the worklet receives it, in render quanta of 128 samples.
function writeFrames(inputRate: number, seconds: number, value: number): ArrayBuffer[] {
  const frames: ArrayBuffer[] = [];
  const write = createPcm16FrameWriter(inputRate, (frame) => frames.push(frame));
  const total = Math.round(inputRate * seconds);
  for (let start = 0; start < total; start += 128) {
    write(new Float32Array(Math.min(128, total - start)).fill(value));
  }
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
