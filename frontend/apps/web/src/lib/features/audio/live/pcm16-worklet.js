// AudioWorklet module for the live transcript preview. It runs on the recorder's
// own AudioContext at the device's rate and posts 100 ms frames of mono 16-bit
// little-endian PCM at 16 kHz, the audio the live transcription socket takes.
// Vite emits this file as it is (`?url&no-inline`), so it imports nothing.

export const PCM16_PROCESSOR = "pcm16-frames";
const TARGET_RATE = 16_000;
export const FRAME_SAMPLES = 1_600;

/**
 * Resamples mono audio to 16 kHz PCM16 frames of FRAME_SAMPLES samples. Each
 * output sample is the average of the input over its own 1/16000 s, a box
 * filter that damps what lies above 8 kHz before it can fold into speech.
 * Positions count in steps of 1/(inputRate * 16000) s, so an input sample spans
 * 16000 steps and an output sample inputRate steps: exact for any pair of rates.
 * @param {number} inputRate
 * @param {(frame: ArrayBuffer) => void} onFrame
 * @returns {(samples: Float32Array) => void}
 */
export function createPcm16FrameWriter(inputRate, onFrame) {
  let frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
  let offset = 0;
  let filled = 0;
  let sum = 0;

  return (samples) => {
    for (const sample of samples) {
      let remaining = TARGET_RATE;
      while (remaining > 0) {
        const taken = Math.min(remaining, inputRate - filled);
        sum += sample * taken;
        filled += taken;
        remaining -= taken;
        if (filled < inputRate) continue;

        const value = Math.max(-1, Math.min(1, sum / inputRate));
        frame.setInt16(offset, Math.round(value < 0 ? value * 0x8000 : value * 0x7fff), true);
        offset += 2;
        filled = 0;
        sum = 0;
        if (offset === frame.byteLength) {
          onFrame(frame.buffer);
          frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
          offset = 0;
        }
      }
    }
  };
}

// Only the worklet scope registers processors; the page and tests import the
// module for the function above.
const scope = /** @type {any} */ (globalThis);
if (typeof scope.registerProcessor === "function") {
  scope.registerProcessor(
    PCM16_PROCESSOR,
    class extends scope.AudioWorkletProcessor {
      constructor() {
        super();
        this.hadInput = false;
        this.write = createPcm16FrameWriter(
          scope.sampleRate,
          /** @param {ArrayBuffer} frame */ (frame) => this.port.postMessage(frame, [frame])
        );
      }

      /** @param {Float32Array[][]} inputs */
      process(inputs) {
        const channel = inputs[0]?.[0];
        // No channel after there was one: the preview disconnected this node,
        // so let it go instead of idling until the recording ends.
        if (!channel) return !this.hadInput;
        this.hadInput = true;
        this.write(channel);
        return true;
      }
    }
  );
}
