import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { EneoError, type EneoErrorCode } from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

import TranscriptPlayer from "./TranscriptPlayer.svelte";

vi.mock("$lib/components/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));
import { toast } from "$lib/components/toast";
import { attachWords, parseTranscript } from "$lib/features/flows/transcriptSegments";
import { withLocale } from "../testLocale";

const TRANSCRIPT = [
  "[00:00:00 - 00:00:04] SPEAKER_00: Hej och välkomna.",
  "[00:00:05 - 00:00:09] SPEAKER_00: Vi börjar snart.",
  "[00:00:12 - 00:00:15] SPEAKER_01: Tack så mycket."
].join("\n");

const SEEK_LABEL = /Spela upp från|Play from/;
const EDIT_LABEL = /Redigera repliken vid|Edit the turn at/;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  vi.mocked(toast.info).mockClear();
  vi.spyOn(console, "error").mockImplementation(() => {});
  // jsdom has no media playback; the component only needs the calls to resolve.
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  // The selection toolbar debounces on animation frames; run them inline.
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 0;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
});

function signed(url = "https://app.test/api/v1/files/f1/download/?token=abc") {
  return vi.fn(async () => ({ url, expires_at: Math.floor(Date.now() / 1000) + 3600 }));
}

const UNAVAILABLE = "flow_run_file_access_audit_unavailable";
const PURGED = "flow_run_input_file_content_unavailable";
const URLS = [0, 1, 2].map((part) => `https://app.test/api/v1/files/part-${part}/download/`);
const PURGED_SENTENCE = m.flow_error_flow_run_input_file_content_unavailable;
const purgedNotice = (n: number) =>
  `${m.flow_run_transcript_part({ n: String(n) })}: ${PURGED_SENTENCE()}`;

function flowError(status: number, eneoCode: EneoErrorCode, code: string): EneoError {
  return new EneoError("refused", "RESPONSE", status, eneoCode, { code });
}

type Answer = "ok" | "purged" | "unavailable" | Promise<void>;

/**
 * A recording by part: what each signing of that part answers in turn; the
 * last answer repeats. A promise is awaited first, then the part is signed.
 */
function recording(...script: Answer[][]) {
  const asked = script.map(() => 0);
  return vi.fn(async (fileIndex: number) => {
    const answers = script[fileIndex];
    const answer = answers[Math.min(asked[fileIndex]++, answers.length - 1)];
    if (answer === "purged") throw flowError(410, 9056, PURGED);
    if (answer === "unavailable") throw flowError(503, 9024, UNAVAILABLE);
    if (answer !== "ok") await answer;
    return { url: URLS[fileIndex], expires_at: Math.floor(Date.now() / 1000) + 3600 };
  });
}

/** The transcript with each speaker's lines in the given part (index). */
function segmentsByPart(partOfSpeaker: Record<string, number>) {
  return parseTranscript(TRANSCRIPT).map((segment) => ({
    ...segment,
    fileIndex: partOfSpeaker[segment.speaker ?? ""] ?? 0
  }));
}

function audioSrc(container: HTMLElement): string | null {
  return container.querySelector("audio")?.getAttribute("src") ?? null;
}

function playButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: m.flow_run_transcript_play() }) as HTMLButtonElement;
}

function partTab(n: number): HTMLButtonElement {
  return screen.getByRole("button", {
    name: m.flow_run_transcript_part({ n: String(n) })
  }) as HTMLButtonElement;
}

function turnBlocks(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>("[data-turn-index]")];
}

function part(container: HTMLElement, segmentIndex: number): HTMLElement {
  return container.querySelector(`[data-segment-index="${segmentIndex}"]`) as HTMLElement;
}

function firstTextNode(element: HTMLElement): Text {
  // Svelte's each-blocks add comment anchors; find the real text node.
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node && !(node.textContent ?? "").trim()) node = walker.nextNode();
  return node as Text;
}

async function selectInPart(
  container: HTMLElement,
  segmentIndex: number,
  start: number,
  end: number
) {
  const node = firstTextNode(part(container, segmentIndex));
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  await fireEvent(document, new Event("selectionchange"));
}

describe("TranscriptPlayer turns", () => {
  it("merges consecutive same-speaker segments into one turn", async () => {
    const getAudioUrl = signed();
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), fileCount: 1, getAudioUrl }
    });

    const blocks = turnBlocks(container);
    expect(blocks).toHaveLength(2);
    expect(blocks[0].textContent).toContain("Hej och välkomna.");
    expect(blocks[0].textContent).toContain("Vi börjar snart.");
    expect(blocks[0].textContent).toContain("SPEAKER_00");
    expect(blocks[1].textContent).toContain("SPEAKER_01");
    // One timestamp per turn, not per fragment.
    expect(screen.getAllByRole("button", { name: SEEK_LABEL })).toHaveLength(2);
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalledWith(0));
  });

  it.each<["sv" | "en", string, boolean, string]>([
    ["sv", "SPEAKER_00", false, "Anna"],
    ["sv", "Överlappande tal – osäker talare", false, "Anna"],
    ["sv", "Talare går inte att avgöra", false, "Anna"],
    ["en", "SPEAKER_00", true, "Overlapping speech – uncertain speaker"]
  ])(
    "shows speaker names and localized review badges (%s, %s)",
    (locale, speaker, provisional, expected) => {
      // Mutant: badge presentation uses a raw status string or a named alias for a marker.
      const restore = withLocale(locale);
      try {
        const segments = parseTranscript(TRANSCRIPT);
        for (const segment of segments.slice(0, 2)) {
          segment.speaker = speaker;
          segment.speakerAttribution = provisional ? "provisional" : "assigned";
        }
        render(TranscriptPlayer, {
          props: { segments, getAudioUrl: signed(), speakerNames: { [speaker]: "Anna" } }
        });

        expect(screen.getAllByText(expected)).toHaveLength(provisional ? 2 : 1);
        expect(screen.getByText("SPEAKER_01")).toBeTruthy();
      } finally {
        restore();
      }
    }
  );

  it("re-flows a reassigned segment into the neighboring turn", () => {
    const { container } = render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        speakerEdits: [
          {
            segment_index: 2,
            char_start: null,
            char_end: null,
            original: null,
            original_speaker: "SPEAKER_01",
            speaker: "SPEAKER_00"
          }
        ]
      }
    });

    // All three segments now belong to SPEAKER_00: one single turn.
    const blocks = turnBlocks(container);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].textContent).toContain("Tack så mycket.");
    expect(screen.queryByText("SPEAKER_01")).toBeNull();
  });

  it("positions the playhead silently when prose or timestamp is clicked", async () => {
    const getAudioUrl = signed();
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), getAudioUrl }
    });
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalled());
    const audio = container.querySelector("audio") as HTMLAudioElement;

    await fireEvent.click(part(container, 2));
    expect(audio.currentTime).toBe(12);

    await fireEvent.click(screen.getAllByRole("button", { name: SEEK_LABEL })[0]);
    expect(audio.currentTime).toBe(0);

    // Positioning never starts playback; Space and the transport do.
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("highlights the spoken part as playback moves", async () => {
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), getAudioUrl: signed() }
    });
    const audio = container.querySelector("audio") as HTMLAudioElement;

    audio.currentTime = 13;
    await fireEvent(audio, new Event("timeupdate"));

    await waitFor(() => expect(part(container, 2).className).toContain("bg-accent-dimmer"));
  });

  it("follows and seeks by word when the segment has stored words", async () => {
    const segments = attachWords(parseTranscript(TRANSCRIPT), {
      alignment: "forced",
      segments: [
        {
          segment_index: 2,
          words: [
            { word: "Tack", start: 12.1, end: 12.4, probability: 0.9 },
            { word: "så", start: 12.5, end: 12.7, probability: 0 },
            { word: "mycket.", start: 12.8, end: 13.4, probability: 0.8 }
          ]
        }
      ]
    });
    const getAudioUrl = signed();
    const { container } = render(TranscriptPlayer, { props: { segments, getAudioUrl } });
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalled());
    const audio = container.querySelector("audio") as HTMLAudioElement;

    // The interpolated word is marked and counted for the reviewer.
    const words = [...part(container, 2).querySelectorAll<HTMLElement>("[data-word-start]")];
    expect(words.map((word) => word.textContent)).toEqual(["Tack", "så", "mycket."]);
    expect(words[1].className).toContain("decoration-wavy");
    expect(words[0].className).not.toContain("decoration-wavy");
    expect(container.querySelector("[data-uncertain-words]")?.textContent).toContain("1");

    // Playback fills the current word solidly inside the softly washed line.
    audio.currentTime = 12.9;
    await fireEvent(audio, new Event("timeupdate"));
    await waitFor(() => expect(words[2].className).toContain("bg-accent-default"));
    expect(words[1].className).not.toContain("bg-accent-default");
    expect(part(container, 2).className).toContain("bg-accent-dimmer");

    // Clicking a word positions the playhead at that word.
    await fireEvent.click(words[1]);
    expect(audio.currentTime).toBe(12.5);
  });

  // Kills two mutants: no retry after any failed load, and every typed
  // refusal told as purged (a retry can help after 503; 404 is no purge).
  it.each([
    ["an untyped failure", () => new Error("network")],
    ["503 access log unavailable", () => flowError(503, 9024, UNAVAILABLE)],
    ["404 not found", () => flowError(404, 9000, "flow_run_input_file_not_found")]
  ])("keeps the transcript readable and offers a retry after %s", async (_name, failure) => {
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: vi.fn(async () => {
          throw failure();
        })
      }
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(m.flow_run_transcript_audio_unavailable());
    expect(alert.className).toContain("text-negative");
    expect(screen.getByRole("button", { name: m.flow_retry() })).toBeTruthy();
    expect(screen.getByText(/Hej och välkomna/)).toBeTruthy();
  });

  it("says that retention removed the recording: a status, no retry", async () => {
    // Kills the mutant that tells purged audio as a playback fault with a
    // retry that asks for the same removed file again.
    render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), getAudioUrl: recording(["purged"]) }
    });

    const status = await screen.findByRole("status");
    expect(status.textContent).toContain(PURGED_SENTENCE());
    expect(status.className).not.toContain("text-negative");
    expect(screen.queryByRole("button", { name: m.flow_retry() })).toBeNull();
    expect(screen.getByText(/Hej och välkomna/)).toBeTruthy();
  });

  it("stays on the part that plays when the reader tries a purged part", async () => {
    // Kills three mutants: the refused switch told as a playback fault
    // (transport and tabs locked while the part may still sound), refused
    // without a word, and the playing part reloaded for nothing.
    const getAudioUrl = recording(["ok"], ["purged"], ["ok"]);
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), fileCount: 3, getAudioUrl }
    });
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));

    await fireEvent.click(partTab(2));

    await waitFor(() => expect(toast.info).toHaveBeenCalledWith(purgedNotice(2)));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(partTab(1).getAttribute("aria-pressed")).toBe("true");
    expect(playButton().disabled).toBe(false);
    expect(getAudioUrl.mock.calls).toEqual([[0], [1]]);

    await fireEvent.click(partTab(3));
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[2]));
    expect(partTab(3).getAttribute("aria-pressed")).toBe("true");
  });

  it("walks on from a purged first part, past another purged one, to a part that plays", async () => {
    // Kills three mutants: part tabs disabled in the purged state (no way
    // on), the first part's status lost after a second purged part was
    // tried, and a part that loads keeping the message of the one before.
    const getAudioUrl = recording(["purged"], ["purged"], ["ok"]);
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), fileCount: 3, getAudioUrl }
    });
    await screen.findByRole("status");

    // Asserted on its own: a dispatched click reaches a disabled button here.
    expect(partTab(2).disabled).toBe(false);
    await fireEvent.click(partTab(2));
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith(purgedNotice(2)));
    // The first part is asked again: its status was hidden for the switch.
    await waitFor(() => expect(getAudioUrl.mock.calls).toEqual([[0], [1], [0]]));
    expect((await screen.findByRole("status")).textContent).toContain(PURGED_SENTENCE());
    expect(partTab(1).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: m.flow_retry() })).toBeNull();

    await fireEvent.click(partTab(3));
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[2]));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(partTab(3).getAttribute("aria-pressed")).toBe("true");
    expect(partTab(1).disabled).toBe(false);
    expect(playButton().disabled).toBe(false);
  });

  it("asks the first part again when a refused switch overtook its first load", async () => {
    // Kills the mutant that leaves the player without a recording and
    // without a message: the overtaken load is dropped, so it is repeated.
    const never = new Promise<void>(() => {});
    const getAudioUrl = recording([never, "ok"], ["purged"]);
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), fileCount: 2, getAudioUrl }
    });
    await waitFor(() => expect(getAudioUrl).toHaveBeenCalledWith(0));

    await fireEvent.click(partTab(2));

    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));
    expect(toast.info).toHaveBeenCalledWith(purgedNotice(2));
    expect(playButton().disabled).toBe(false);
  });

  it("does not let a sample of a purged part stop the part that plays", async () => {
    // Kills the mutant that sets the sample's end before its part has
    // loaded: the part that plays would pause there at its next tick.
    const { component, container } = render(TranscriptPlayer, {
      props: {
        segments: segmentsByPart({ SPEAKER_00: 1, SPEAKER_01: 0 }),
        fileCount: 2,
        getAudioUrl: recording(["ok"], ["purged"])
      }
    });
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));
    const audio = container.querySelector("audio") as HTMLAudioElement;

    component.playSpeakerSample("SPEAKER_00");
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith(purgedNotice(2)));
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();
    audio.currentTime = 600;
    await fireEvent(audio, new Event("timeupdate"));

    expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled();
  });

  it("reloads the part before by the retry after a switch that failed", async () => {
    // Kills the mutant that drops the retry (or the part before) when a
    // switch fails for a reason that is no purge: the tabs are disabled then.
    let finishRetry!: () => void;
    const retried = new Promise<void>((resolve) => (finishRetry = resolve));
    const getAudioUrl = recording(["ok", retried], ["unavailable"]);
    const { container } = render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), fileCount: 2, getAudioUrl }
    });
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));

    await fireEvent.click(partTab(2));
    await fireEvent.click(await screen.findByRole("button", { name: m.flow_retry() }));

    // The load has started, not finished: the fault is gone, the transport waits.
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(getAudioUrl).toHaveBeenLastCalledWith(0);
    expect(playButton().disabled).toBe(true);
    finishRetry();
    await waitFor(() => expect(playButton().disabled).toBe(false));
    expect(partTab(1).getAttribute("aria-pressed")).toBe("true");
    expect(partTab(2).disabled).toBe(false);
  });

  it("plays nothing of a part once the server says it is purged", async () => {
    // Part 2 loads for a sample (autoplay still pending: no metadata here),
    // a switch back fails, and the retry of part 2 answers purged. Kills
    // three mutants: the part goes on playing from its old link, the
    // pending autoplay starts later, and "listen" plays the old link. A
    // fourth: "listen" for a sample in another part is refused as well.
    const getAudioUrl = recording(["ok", "unavailable", "ok"], ["ok", "purged"]);
    const { component, container } = render(TranscriptPlayer, {
      props: {
        segments: segmentsByPart({ SPEAKER_00: 1, SPEAKER_01: 0 }),
        fileCount: 2,
        getAudioUrl
      }
    });
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));
    const audio = container.querySelector("audio") as HTMLAudioElement;
    component.playSpeakerSample("SPEAKER_00");
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[1]));
    await fireEvent.click(partTab(1));
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();

    await fireEvent.click(await screen.findByRole("button", { name: m.flow_retry() }));
    await screen.findByRole("status");

    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1);
    audio.currentTime = 7;
    await fireEvent(audio, new Event("loadedmetadata"));
    component.playSpeakerSample("SPEAKER_00");
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(audio.currentTime).toBe(7);

    // A sample in the other part loads, plays and stops at its end; so does
    // the next sample in that part, now the current one. Kills three more:
    // a sample that plays past its end after a load, one that does so in
    // the current part, and "listen" still refused after the purged part.
    component.playSpeakerSample("SPEAKER_01");
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));
    expect(screen.queryByRole("status")).toBeNull();
    for (const sample of [1, 2]) {
      if (sample === 1) await fireEvent(audio, new Event("loadedmetadata"));
      else component.playSpeakerSample("SPEAKER_01");
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(sample);
      vi.mocked(HTMLMediaElement.prototype.pause).mockClear();
      audio.currentTime = 600;
      await fireEvent(audio, new Event("timeupdate"));
      expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1);
    }
  });

  it("asks the part again where it was, and playing if it was, after a refused switch hid its fault", async () => {
    // Kills the mutant that reloads the part from its start, or silent.
    const getAudioUrl = recording(["ok"], ["unavailable"], ["purged"]);
    const { component, container } = render(TranscriptPlayer, {
      props: {
        segments: segmentsByPart({ SPEAKER_00: 2, SPEAKER_01: 0 }),
        fileCount: 3,
        getAudioUrl
      }
    });
    await waitFor(() => expect(audioSrc(container)).toBe(URLS[0]));
    const audio = container.querySelector("audio") as HTMLAudioElement;
    await fireEvent.click(partTab(2));
    await screen.findByRole("alert");
    audio.currentTime = 42;
    Object.defineProperty(audio, "paused", { configurable: true, get: () => false });

    component.playSpeakerSample("SPEAKER_00");

    await waitFor(() => expect(getAudioUrl.mock.calls).toEqual([[0], [1], [2], [0]]));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    audio.currentTime = 0;
    await fireEvent(audio, new Event("loadedmetadata"));
    expect(audio.currentTime).toBe(42);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
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

describe("TranscriptPlayer editing", () => {
  it("offers no edit affordances in read-only mode", () => {
    render(TranscriptPlayer, {
      props: { segments: parseTranscript(TRANSCRIPT), getAudioUrl: signed() }
    });

    expect(screen.queryByRole("button", { name: EDIT_LABEL })).toBeNull();
    expect(screen.queryByRole("button", { name: /Byt talare|Change the speaker/ })).toBeNull();
  });

  it("edits a whole turn in place and cancels on Escape", async () => {
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine: vi.fn(async () => true)
      }
    });

    await fireEvent.click(screen.getAllByRole("button", { name: EDIT_LABEL })[0]);
    const editor = screen.getByRole("textbox", { name: EDIT_LABEL });
    expect(editor.textContent).toBe("Hej och välkomna. Vi börjar snart.");

    await fireEvent.keyDown(editor, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: EDIT_LABEL })).toBeNull();
  });

  it("routes a turn edit to the changed segment on Enter", async () => {
    const onSaveLine = vi.fn(async () => true);
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine
      }
    });

    await fireEvent.click(screen.getAllByRole("button", { name: EDIT_LABEL })[0]);
    const editor = screen.getByRole("textbox", { name: EDIT_LABEL });
    editor.textContent = "Hej och välkomna. Vi börjar nu.";
    await fireEvent.keyDown(editor, { key: "Enter" });

    expect(onSaveLine).toHaveBeenCalledTimes(1);
    expect(onSaveLine).toHaveBeenCalledWith(1, "Vi börjar nu.", { suggest: true });
    await waitFor(() => expect(screen.queryByRole("textbox", { name: EDIT_LABEL })).toBeNull());
  });

  it("does not commit an Enter that belongs to IME composition", async () => {
    const onSaveLine = vi.fn(async () => true);
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine
      }
    });

    await fireEvent.click(screen.getAllByRole("button", { name: EDIT_LABEL })[1]);
    const editor = screen.getByRole("textbox", { name: EDIT_LABEL });
    editor.textContent = "Tack.";
    await fireEvent.keyDown(editor, { key: "Enter", isComposing: true });

    expect(onSaveLine).not.toHaveBeenCalled();
  });

  it("commits on blur only when the text changed", async () => {
    const onSaveLine = vi.fn(async () => true);
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine
      }
    });

    await fireEvent.click(screen.getAllByRole("button", { name: EDIT_LABEL })[1]);
    let editor = screen.getByRole("textbox", { name: EDIT_LABEL });
    await fireEvent.blur(editor);
    expect(onSaveLine).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: EDIT_LABEL })).toBeNull();

    await fireEvent.click(screen.getAllByRole("button", { name: EDIT_LABEL })[1]);
    editor = screen.getByRole("textbox", { name: EDIT_LABEL });
    editor.textContent = "Tack så väldigt mycket.";
    await fireEvent.blur(editor);
    expect(onSaveLine).toHaveBeenCalledWith(2, "Tack så väldigt mycket.", { suggest: true });
  });

  it("keeps playback shortcuts out of the editor", async () => {
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine: vi.fn(async () => true)
      }
    });

    await fireEvent.click(screen.getAllByRole("button", { name: EDIT_LABEL })[1]);
    const editor = screen.getByRole("textbox", { name: EDIT_LABEL });
    await fireEvent.keyDown(editor, { key: " " });

    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("marks only the corrected span and reverts through onRevertLine", async () => {
    const onRevertLine = vi.fn();
    const { container } = render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        corrections: [
          { segment_index: 0, char_start: 0, char_end: 3, original: "Hej", corrected: "Tja" }
        ],
        onSaveLine: vi.fn(async () => true),
        onRevertLine
      }
    });

    const marked = screen.getByText("Tja");
    expect(marked.className).toContain("underline");
    // The rest of the line is not presented as corrected.
    expect(part(container, 0).textContent).toContain("och välkomna.");
    expect(part(container, 0).querySelectorAll(".underline")).toHaveLength(1);

    await fireEvent.click(
      screen.getByRole("button", { name: /Ångra rättningarna|Undo the corrections/ })
    );
    expect(onRevertLine).toHaveBeenCalledWith(0);
  });
});

describe("TranscriptPlayer speaker re-attribution", () => {
  it("turns a text selection into a floating change-speaker toolbar", async () => {
    const onSaveSpeakerEdits = vi.fn(async () => true);
    const { container } = render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine: vi.fn(async () => true),
        onSaveSpeakerEdits
      }
    });

    await selectInPart(container, 2, 0, 4);
    const toolbar = await screen.findByRole("toolbar");

    await fireEvent.click(within(toolbar).getByText("SPEAKER_00"));

    expect(onSaveSpeakerEdits).toHaveBeenCalledWith([
      { segment_index: 2, char_start: 0, char_end: 4, speaker: "SPEAKER_00" }
    ]);
  });

  it("reassigns a whole turn through the gutter badge menu", async () => {
    const onSaveSpeakerEdits = vi.fn(async () => true);
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine: vi.fn(async () => true),
        onSaveSpeakerEdits
      }
    });

    const trigger = screen.getAllByRole("button", {
      name: /Byt talare för repliken|Change the speaker of the turn/
    })[1];
    await fireEvent.click(trigger);
    const items = await screen.findAllByRole("menuitem");
    const item = items.find((candidate) => candidate.textContent?.includes("SPEAKER_00"));
    expect(item).toBeTruthy();
    await fireEvent.click(item!);

    await waitFor(() =>
      expect(onSaveSpeakerEdits).toHaveBeenCalledWith([
        { segment_index: 2, char_start: 0, char_end: 15, speaker: "SPEAKER_00" }
      ])
    );
  });

  it("shows no toolbar when speaker editing is not offered", async () => {
    const { container } = render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        editable: true,
        onSaveLine: vi.fn(async () => true)
      }
    });

    await selectInPart(container, 2, 0, 4);

    expect(screen.queryByRole("toolbar")).toBeNull();
  });
});

describe("speaker review", () => {
  const reviewed = [
    {
      index: 0,
      fileIndex: 0,
      start: 0,
      end: 1,
      speaker: "SPEAKER_00",
      text: "Tydligt.",
      speakerAttribution: "assigned"
    },
    {
      index: 1,
      fileIndex: 0,
      start: 1,
      end: 2,
      speaker: "SPEAKER_00",
      text: "Samtidigt.",
      speakerAttribution: "provisional",
      overlapIds: ["file:overlap_0000"]
    },
    {
      index: 2,
      fileIndex: 0,
      start: 2,
      end: 3,
      speaker: "SPEAKER_00",
      text: "Tydligt igen.",
      speakerAttribution: "assigned"
    }
  ];
  it("keeps overlap boundaries and does not display the proposed name as settled", () => {
    const { container } = render(TranscriptPlayer, {
      props: {
        segments: reviewed,
        getAudioUrl: signed(),
        speakerNames: { SPEAKER_00: "Anna" }
      }
    });
    expect(turnBlocks(container)).toHaveLength(3);
    const provisional = turnBlocks(container)[1];
    expect(provisional.textContent).toContain("Överlappande tal – osäker talare");
    expect(provisional.textContent).not.toContain("Anna");
    expect(within(provisional).getByText("Granskningsdetaljer")).toBeTruthy();
  });
  it("offers an explicit unresolved choice even when the proposed speaker is null and audio is missing", async () => {
    const save = vi.fn(async () => true);
    const { container } = render(TranscriptPlayer, {
      props: {
        segments: [{ ...reviewed[1], index: 0, speaker: null }],
        editable: true,
        getAudioUrl: vi.fn(async () => {
          throw new Error("audio missing");
        }),
        onSaveSpeakerEdits: save
      }
    });
    await fireEvent.click(
      within(turnBlocks(container)[0]).getByRole("button", {
        name: /talare.*repliken|speaker.*turn/i
      })
    );
    await fireEvent.click(
      await screen.findByRole("menuitem", { name: "Talare går inte att avgöra" })
    );
    expect(save).toHaveBeenCalledWith([
      expect.objectContaining({ segment_index: 0, speaker: null })
    ]);
  });
});
