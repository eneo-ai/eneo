import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TranscriptPlayer from "./TranscriptPlayer.svelte";
import { parseTranscript } from "$lib/features/flows/transcriptSegments";

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

  it("shows the reviewer's names on the raw labels", () => {
    render(TranscriptPlayer, {
      props: {
        segments: parseTranscript(TRANSCRIPT),
        getAudioUrl: signed(),
        speakerNames: { SPEAKER_00: "Anna" }
      }
    });

    expect(screen.getByText("Anna")).toBeTruthy();
    expect(screen.getByText("SPEAKER_01")).toBeTruthy();
  });

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
    expect(screen.getByText(/Hej och välkomna/)).toBeTruthy();
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
