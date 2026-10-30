// AudioWorklet module for the live transcript in the run form
// (src/features/flows/runs/recording/live-transcript.ts). It runs on the
// recorder's own AudioContext at the device's rate and posts 100 ms frames of
// mono 16-bit little-endian PCM at 16 kHz, the audio the live transcription
// socket takes. It is served as a file of its own, because the app's CSP
// takes no worklet from a data: URL, and so it imports nothing.
//
// Messages from the page: "flush" asks for the frame in progress, however
// short, answered by "flushed"; "pause" drops the frame in progress and hears
// nothing until "resume", which is answered by "resumed" (every frame posted
// before that answer was heard before the resume).

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600;

/**
 * Each output sample is the average of the input over its own 1/16000 s, a
 * box filter that damps what lies above 8 kHz before it can fold into speech.
 * Positions count in steps of 1/(inputRate * 16000) s, so an input sample
 * spans 16000 steps and an output sample inputRate steps: exact for any pair
 * of rates.
 */
function createPcm16FrameWriter(inputRate, onFrame) {
  let frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
  let offset = 0;
  let filled = 0;
  let sum = 0;

  const emit = (buffer) => {
    onFrame(buffer);
    frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
    offset = 0;
  };

  return {
    discard() {
      frame = new DataView(new ArrayBuffer(FRAME_SAMPLES * 2));
      offset = 0;
      filled = 0;
      sum = 0;
    },
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
    flush() {
      if (offset > 0) emit(frame.buffer.slice(0, offset));
    }
  };
}

registerProcessor(
  "pcm16-frames",
  class extends AudioWorkletProcessor {
    constructor() {
      super();
      this.writer = createPcm16FrameWriter(sampleRate, (frame) =>
        this.port.postMessage(frame, [frame])
      );
      this.hadInput = false;
      this.paused = false;
      this.port.onmessage = (event) => {
        if (event.data === "pause") {
          this.paused = true;
          this.writer.discard();
        } else if (event.data === "resume") {
          this.paused = false;
          this.port.postMessage("resumed");
        } else if (event.data === "flush") {
          this.writer.flush();
          this.port.postMessage("flushed");
        }
      };
    }

    process(inputs) {
      const channel = inputs[0] && inputs[0][0];
      // No channel after there was one: the page disconnected this node, so
      // let it go instead of idling until the recording ends.
      if (!channel) return !this.hadInput;
      this.hadInput = true;
      if (!this.paused) this.writer.write(channel);
      return true;
    }
  }
);
