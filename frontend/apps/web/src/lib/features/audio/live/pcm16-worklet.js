// AudioWorklet module for the live transcript preview. It runs on the recorder's
// own AudioContext at the device's rate and posts 100 ms frames of mono 16-bit
// little-endian PCM at 16 kHz, the audio the live transcription socket takes.
// Vite emits this file as it is (`?url&no-inline`), so it imports nothing.

export const PCM16_PROCESSOR = "pcm16-frames";
// The page asks for the frame in progress with PCM16_FLUSH; the processor posts
// it, however short, and then PCM16_FLUSHED.
export const PCM16_FLUSH = "flush";
export const PCM16_FLUSHED = "flushed";
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
 * @returns {{ write: (samples: Float32Array) => void, flush: () => void }}
 */
export function createPcm16FrameWriter(inputRate, onFrame) {
  let frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
  let offset = 0;
  let filled = 0;
  let sum = 0;

  /** @param {ArrayBuffer} buffer */
  const emit = (buffer) => {
    onFrame(buffer);
    frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
    offset = 0;
  };

  return {
    write(samples) {
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
          if (offset === frame.byteLength) emit(frame.buffer);
        }
      }
    },
    // The end of a recording: the frame in progress goes out as it is.
    flush() {
      if (offset > 0) emit(frame.buffer.slice(0, offset));
    }
  };
}

/**
 * What the processor does, apart from the worklet scope so a test can drive it:
 * frames go out through `port`, and PCM16_FLUSH is answered with the frame in
 * progress and PCM16_FLUSHED.
 * @param {number} inputRate
 * @param {{ postMessage: (message: unknown, transfer?: Transferable[]) => void, onmessage: ((event: { data: unknown }) => void) | null }} port
 * @returns {(inputs: Float32Array[][]) => boolean} the processor's `process`
 */
export function createPcm16Processor(inputRate, port) {
  const writer = createPcm16FrameWriter(inputRate, (frame) => port.postMessage(frame, [frame]));
  let hadInput = false;
  port.onmessage = (event) => {
    if (event.data !== PCM16_FLUSH) return;
    writer.flush();
    port.postMessage(PCM16_FLUSHED);
  };
  return (inputs) => {
    const channel = inputs[0]?.[0];
    // No channel after there was one: the preview disconnected this node, so
    // let it go instead of idling until the recording ends.
    if (!channel) return !hadInput;
    hadInput = true;
    writer.write(channel);
    return true;
  };
}

// Only the worklet scope registers processors; the page and tests import the
// module for the functions above.
const scope = /** @type {any} */ (globalThis);
if (typeof scope.registerProcessor === "function") {
  scope.registerProcessor(
    PCM16_PROCESSOR,
    class extends scope.AudioWorkletProcessor {
      constructor() {
        super();
        this.processInputs = createPcm16Processor(scope.sampleRate, this.port);
      }

      /** @param {Float32Array[][]} inputs */
      process(inputs) {
        return this.processInputs(inputs);
      }
    }
  );
}
