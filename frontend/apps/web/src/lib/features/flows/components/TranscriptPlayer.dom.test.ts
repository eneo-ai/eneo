import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TranscriptPlayer from "./TranscriptPlayer.svelte";
import { parseTranscript } from "$lib/features/flows/transcriptSegments";

const TRANSCRIPT = [
  "[00:00:00 - 00:00:04] SPEAKER_00: Hej och välkomna.",
  "[00:00:05 - 00:00:09] SPEAKER_01: Tack så mycket.",
  "[00:00:12 - 00:00:15] SPEAKER_00: Vi börjar."
].join("\n");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  // jsdom has no media playback; the component only needs the calls to resolve.
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});

function signed(url = "https://app.test/api/v1/files/f1/download/?token=abc") {
  return vi.fn(async () => ({ url, expires_at: Math.floor(Date.now() / 1000) + 3600 }));
}

describe("TranscriptPlayer", () => {
  it("renders one seekable line per segment with its speaker and time", async () => {
    const getAudioUrl = signed();
    render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), fileCount: 1, getAudioUrl }
    });

    const lines = screen.getAllByRole("button", {
      name: /Hej och välkomna|Tack så mycket|Vi börjar/
    });
    expect(lines).toHaveLength(3);
    expect(lines[1].textContent).toContain("SPEAKER_01");
    expect(lines[1].textContent).toContain("00:05");
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalledWith(0));
  });

  it("shows the reviewer's names on the raw labels", () => {
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        speakerNames: { SPEAKER_00: "Anna" }
      }
    });

    expect(screen.getAllByText("Anna")).toHaveLength(2);
    expect(screen.getByText("SPEAKER_01")).toBeTruthy();
  });

  it("seeks the audio and highlights the line that was clicked", async () => {
    const getAudioUrl = signed();
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), getAudioUrl }
    });
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalled());
    const audio = container.querySelector("audio") as HTMLAudioElement;

    await fireEvent.click(screen.getByRole("button", { name: /Tack så mycket/ }));

    expect(audio.currentTime).toBe(5);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    const line = container.querySelector('[data-segment-index="1"]');
    expect(line?.getAttribute("aria-current")).toBe("true");
  });

  it("moves the highlight with playback", async () => {
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), getAudioUrl: signed() }
    });
    const audio = container.querySelector("audio") as HTMLAudioElement;

    audio.currentTime = 13;
    await fireEvent(audio, new Event("timeupdate"));

    await waitFor(() =>
      expect(
        container.querySelector('[data-segment-index="2"]')?.getAttribute("aria-current")
      ).toBe("true")
    );
  });

  it("keeps the transcript readable when the audio cannot be signed", async () => {
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: vi.fn(async () => {
          throw new Error("410");
        })
      }
    });

    await waitFor(() =>
      expect(screen.getByText(/kan inte spelas upp|cannot be played/)).toBeTruthy()
    );
    const line = screen.getByRole("button", { name: /Hej och välkomna/ }) as HTMLButtonElement;
    expect(line.disabled).toBe(true);
  });

  it("waits for the audio files and then signs the first one exactly once", async () => {
    const getAudioUrl = signed();
    const { rerender } = render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        fileCount: 0,
        getAudioUrl,
        audioPending: true
      }
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(getAudioUrl).not.toHaveBeenCalled();

    await rerender({
      segments: parseTranscript(TRANSCRIPT),
      fileCount: 1,
      getAudioUrl,
      audioPending: false
    });
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalledTimes(1));

    // Unrelated prop churn (new segment arrays, names) must not sign again.
    await rerender({
      segments: parseTranscript(TRANSCRIPT),
      fileCount: 1,
      getAudioUrl,
      audioPending: false,
      speakerNames: { SPEAKER_00: "Anna" }
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(getAudioUrl).toHaveBeenCalledTimes(1);
  });

  it("falls back to plain text when the transcript has no timestamps", () => {
    render(TranscriptPlayer, {
      props: { segments: [], getAudioUrl: signed(), textFallback: "Bara text." }
    });

    expect(screen.getByText("Bara text.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
