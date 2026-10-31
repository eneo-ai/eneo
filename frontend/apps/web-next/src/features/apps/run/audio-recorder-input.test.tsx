// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import type { InputField } from "../apps";
import { AudioRecorderInput } from "./audio-recorder-input";

const saveBlob = vi.hoisted(() => vi.fn());
vi.mock("@/features/files/signed-file-url", () => ({ saveBlob }));

const getUserMedia = vi.fn<() => Promise<MediaStream>>();
const stopTrack = vi.fn();
const closeContext = vi.fn().mockResolvedValue(undefined);
let stream: MediaStream;
let track: MediaStreamTrack;
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
  data(value = "audio") {
    const event = new Event("dataavailable");
    Object.defineProperty(event, "data", { value: new Blob([value]) });
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
  track = Object.assign(new EventTarget(), { stop: stopTrack }) as unknown as MediaStreamTrack;
  stream = Object.assign(new EventTarget(), {
    getTracks: () => [track],
    getAudioTracks: () => [track]
  }) as unknown as MediaStream;
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
  vi.useRealTimers();
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
  expect(recorded.name).toMatch(/^Inspelning \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.webm$/);
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(closeContext).toHaveBeenCalledTimes(1);
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:recording");
});

it("saves the captured audio with its dated filename, including while queued", async () => {
  const props = { field, onAddFiles: vi.fn(), onRemoveFile: vi.fn() };
  const { rerender } = renderInApp(<AudioRecorderInput {...props} files={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  const stop = await screen.findByRole("button", { name: "Stoppa inspelning" });
  act(() => Recorder.instances[0]!.data());
  fireEvent.click(stop);
  fireEvent.click(await screen.findByRole("button", { name: "Spara som fil" }));
  const [file, name] = saveBlob.mock.calls[0]! as [File, string];
  expect(file.size).toBe(5);
  expect(name).toBe(file.name);
  expect(name).toMatch(/^Inspelning \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.webm$/);
  rerender(
    <AudioRecorderInput
      {...props}
      files={[{ key: "r1", name, size: 5, mimetype: "audio/webm", uploading: false, fileId: "f1" }]}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Spara som fil" }));
  expect(saveBlob).toHaveBeenLastCalledWith(file, name);
  // A rejected or failed upload removes its chip, never the locally captured audio.
  rerender(<AudioRecorderInput {...props} files={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Spara som fil" }));
  expect(saveBlob).toHaveBeenLastCalledWith(file, name);
});

it("retains the preview when discard is cancelled and releases it only after confirmation", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  const stop = await screen.findByRole("button", { name: "Stoppa inspelning" });
  act(() => Recorder.instances[0]!.data());
  fireEvent.click(stop);
  fireEvent.click(await screen.findByRole("button", { name: "Kassera" }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Spara som fil" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Kassera" }));
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Kassera" })
  );
  expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:recording");
  expect(screen.queryByRole("button", { name: "Spara som fil" })).toBeNull();
  expect(unloadIsGuarded()).toBe(false);
});

it.each(["inactive", "ended", "error"])(
  "preserves captured audio and finalizes once after %s",
  async (eventName) => {
    const { container } = show();
    fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
    await screen.findByRole("button", { name: "Stoppa inspelning" });
    const recorder = Recorder.instances[0]!;
    const stop = vi.spyOn(recorder, "stop");
    act(() => {
      recorder.data();
      const target = eventName === "inactive" ? stream : eventName === "ended" ? track : recorder;
      target.dispatchEvent(new Event(eventName));
      target.dispatchEvent(new Event(eventName));
    });
    fireEvent.click(await screen.findByRole("button", { name: "Spara som fil" }));
    expect((saveBlob.mock.calls[0]![0] as File).size).toBe(5);
    expect(stop).toHaveBeenCalledTimes(1);
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(closeContext).toHaveBeenCalledTimes(1);
    expect(
      within(container).getByText(
        eventName === "error"
          ? messages.recording_saved_after_error
          : "Inspelningen stoppades eftersom mikrofonen kopplades bort."
      )
    ).toBeTruthy();
    act(() => {
      stream.dispatchEvent(new Event("inactive"));
      track.dispatchEvent(new Event("ended"));
    });
    expect(stop).toHaveBeenCalledTimes(1);
  }
);

it("waits for the browser's final chunk after an already inactive recorder fails", async () => {
  const { container } = show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  await screen.findByRole("button", { name: "Stoppa inspelning" });
  const recorder = Recorder.instances[0]!;
  const stop = vi.spyOn(recorder, "stop");
  act(() => {
    recorder.data();
    recorder.state = "inactive";
    recorder.dispatchEvent(new Event("error"));
  });
  expect(unloadIsGuarded()).toBe(true);
  expect(stop).not.toHaveBeenCalled();
  act(() => {
    recorder.data();
    recorder.dispatchEvent(new Event("stop"));
    recorder.dispatchEvent(new Event("stop"));
  });
  fireEvent.click(await screen.findByRole("button", { name: "Spara som fil" }));
  expect((saveBlob.mock.calls[0]![0] as File).size).toBe(10);
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Kassera" }));
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Kassera" })
  );
  expect(within(container).queryByText(messages.recording_saved_after_error)).toBeNull();
});

it("stops a stalled capture even without animation frames and retains nonempty chunks", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1)
  );
  const { container } = show();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" })));
  act(() => Recorder.instances[0]!.data());
  await act(async () => vi.advanceTimersByTime(15_000));
  act(() => Recorder.instances[0]!.data(""));
  await act(async () => vi.advanceTimersByTime(5_001));
  expect(within(container).getByText(messages.recording_stalled)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Spara som fil" }));
  expect((saveBlob.mock.calls[0]![0] as File).size).toBe(5);
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("explains when a stopped recording contains no audio", async () => {
  const { container } = show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  fireEvent.click(await screen.findByRole("button", { name: "Stoppa inspelning" }));
  expect(await within(container).findByText("Ingen ljuddata spelades in")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Spara som fil" })).toBeNull();
});

it("does not offer recovery of audio that was never captured before disconnect", async () => {
  const { container } = show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  await screen.findByRole("button", { name: "Stoppa inspelning" });
  act(() => stream.dispatchEvent(new Event("inactive")));
  expect(await within(container).findByText("Ingen ljuddata spelades in")).toBeTruthy();
  expect(
    within(container).queryByText("Inspelningen stoppades eftersom mikrofonen kopplades bort.")
  ).toBeNull();
  expect(screen.queryByRole("button", { name: "Spara som fil" })).toBeNull();
});

it.each([
  ["NotAllowedError", messages.recording_error_permission, 1],
  ["NotFoundError", "Ingen mikrofon hittades. Anslut en mikrofon och försök igen.", 2],
  ["NotReadableError", messages.recording_error_not_readable, 1],
  ["OverconstrainedError", messages.recording_error_overconstrained, 2],
  ["SecurityError", messages.recording_error_security, 1],
  ["NotSupportedError", messages.recording_error_not_supported, 1]
])(
  "explains %s and exposes technical diagnostics without retrying blocked access",
  async (name, message, calls) => {
    getUserMedia.mockRejectedValue(new DOMException("Microphone refused", name as string));
    const { container } = show();
    fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
    expect(await within(container).findByText(message as string)).toBeTruthy();
    expect(getUserMedia).toHaveBeenCalledTimes(calls as number);
    fireEvent.click(screen.getByRole("button", { name: "Visa diagnostik" }));
    expect(screen.getByText(/Microphone refused/)).toBeTruthy();
  }
);

it("retries compatible constraint failures with audio only, then records normally", async () => {
  getUserMedia.mockRejectedValueOnce(
    new DOMException("Constraint unavailable", "OverconstrainedError")
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  await screen.findByRole("button", { name: "Stoppa inspelning" });
  expect(getUserMedia).toHaveBeenNthCalledWith(2, { audio: true });
});

it("does not request a fallback microphone after unmount", async () => {
  let reject!: (error: unknown) => void;
  getUserMedia.mockReturnValue(
    new Promise((_resolve, rejectPromise) => {
      reject = rejectPromise;
    })
  );
  const { unmount } = show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  unmount();
  await act(async () => reject(new DOMException("Unavailable", "NotFoundError")));
  expect(getUserMedia).toHaveBeenCalledTimes(1);
});

it("releases the fallback stream while applying optional constraints after unmount", async () => {
  let applied!: () => void;
  const applyConstraints = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        applied = resolve;
      })
  );
  Object.assign(track, { applyConstraints });
  getUserMedia.mockRejectedValueOnce(
    new DOMException("Constraint unavailable", "OverconstrainedError")
  );
  const { unmount } = show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  await waitFor(() => expect(applyConstraints).toHaveBeenCalledTimes(1));
  unmount();
  expect(stopTrack).toHaveBeenCalledTimes(1);
  await act(async () => applied());
  expect(Recorder.instances).toHaveLength(0);
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("removes the stall timer and releases active capture on unmount", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1)
  );
  const { unmount } = show();
  const idleTimers = vi.getTimerCount();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" })));
  expect(vi.getTimerCount()).toBeGreaterThan(idleTimers);
  unmount();
  expect(vi.getTimerCount()).toBe(idleTimers);
  await act(async () => vi.advanceTimersByTime(30_000));
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(closeContext).toHaveBeenCalledTimes(1);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("explains unsupported microphone APIs before requesting access", async () => {
  vi.stubGlobal("MediaRecorder", undefined);
  show();
  fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  expect(await screen.findByText(messages.recording_error_not_supported)).toBeTruthy();
  expect(getUserMedia).not.toHaveBeenCalled();
});

/** Whether the browser would ask before unloading the page now. */
function unloadIsGuarded(): boolean {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

it("warns before a reload loses a recording, until it is queued and uploaded", async () => {
  const props = { field, onAddFiles: vi.fn(), onRemoveFile: vi.fn() };
  const { rerender } = renderInApp(<AudioRecorderInput {...props} files={[]} />);
  expect(unloadIsGuarded()).toBe(false);

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Starta inspelning" }));
  });
  const stop = await screen.findByRole("button", { name: "Stoppa inspelning" });
  expect(unloadIsGuarded()).toBe(true);

  const recorder = Recorder.instances[0]!;
  act(() => recorder.data());
  // The recorder finalizes the audio after Stop; the page stays guarded meanwhile.
  recorder.stop = () => {
    recorder.state = "inactive";
  };
  fireEvent.click(stop);
  expect(unloadIsGuarded()).toBe(true);
  act(() => {
    recorder.dispatchEvent(new Event("stop"));
  });
  await screen.findByRole("button", { name: "Använd denna inspelning" });
  // Recorded but not queued yet.
  expect(unloadIsGuarded()).toBe(true);

  const queued = { key: "r1", name: "recording.webm", size: 5, mimetype: "audio/webm" };
  rerender(<AudioRecorderInput {...props} files={[{ ...queued, uploading: true }]} />);
  expect(unloadIsGuarded()).toBe(true);

  rerender(
    <AudioRecorderInput {...props} files={[{ ...queued, uploading: false, fileId: "f1" }]} />
  );
  expect(unloadIsGuarded()).toBe(false);
});
