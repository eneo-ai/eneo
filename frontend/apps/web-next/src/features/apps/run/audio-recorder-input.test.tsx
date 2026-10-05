// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { InputField } from "../apps";
import { AudioRecorderInput } from "./audio-recorder-input";

const getUserMedia = vi.fn<() => Promise<MediaStream>>();
const stopTrack = vi.fn();
const closeContext = vi.fn().mockResolvedValue(undefined);
const stream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream;
let recorderFails = false;
class Recorder extends EventTarget {
  static instances: Recorder[] = [];
  static isTypeSupported = () => false;
  state = "inactive";
  mimeType = "audio/webm;codecs=opus";
  constructor() {
    super();
    if (recorderFails) throw new Error("Recorder unavailable");
    Recorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    queueMicrotask(() => this.dispatchEvent(new Event("stop")));
  }
  data() {
    const event = new Event("dataavailable");
    Object.defineProperty(event, "data", { value: new Blob(["audio"]) });
    this.dispatchEvent(event);
  }
}
const field: InputField = {
  type: "audio-recorder",
  limit: { max_files: 1, max_size: 1000000 },
  accepted_file_types: [{ mimetype: "audio/webm", extensions: ["webm"], size_limit: 1000000 }]
};
function show() {
  const onAddFiles = vi.fn();
  return {
    ...renderInApp(
      <AudioRecorderInput field={field} files={[]} onAddFiles={onAddFiles} onRemoveFile={vi.fn()} />
    ),
    onAddFiles
  };
}
beforeEach(() => {
  Recorder.instances = [];
  recorderFails = false;
  getUserMedia.mockResolvedValue(stream);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal(
    "AudioContext",
    class {
      close = closeContext;
      createAnalyser() {
        return { fftSize: 8, getFloatTimeDomainData: vi.fn() };
      }
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
    }
  );
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:recording");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("releases permission granted after unmount, and prevents concurrent capture starts", async () => {
  let grant!: (stream: MediaStream) => void;
  getUserMedia.mockReturnValue(
    new Promise((resolve) => {
      grant = resolve;
    })
  );
  const { unmount } = show();
  const start = screen.getByRole("button", { name: "Starta inspelning" });
  fireEvent.click(start);
  fireEvent.click(start);
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  expect(start.getAttribute("aria-busy")).toBe("true");
  unmount();
  await act(async () => grant(stream));
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(Recorder.instances).toHaveLength(0);
});

it("releases microphone and audio context when recorder setup fails", async () => {
  recorderFails = true;
  show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  await waitFor(() => expect(stopTrack).toHaveBeenCalledTimes(1));
  expect(closeContext).toHaveBeenCalledTimes(1);
});

it("queues a recording using the accepted MIME essence and releases capture", async () => {
  const { onAddFiles, unmount } = show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  const stop = await screen.findByRole("button", { name: "Stoppa inspelning" });
  act(() => Recorder.instances[0]!.data());
  fireEvent.click(stop);
  fireEvent.click(await screen.findByRole("button", { name: "Använd denna inspelning" }));
  const recorded = onAddFiles.mock.calls[0]![0][0] as File;
  expect(recorded.type).toBe("audio/webm");
  expect(recorded.name).toBe("recording.webm");
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(closeContext).toHaveBeenCalledTimes(1);
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:recording");
});
