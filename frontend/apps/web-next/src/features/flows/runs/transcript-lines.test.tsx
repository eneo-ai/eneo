// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { TranscriptSpeakerReview } from "./runs-api";
import {
  parseSegments,
  shownSegments,
  type TranscriptSegment,
  type TranscriptTarget
} from "./transcript";
import { correctionSet, knownSpeakers, type CorrectionSet } from "./transcript-corrections";
import { TranscriptLines } from "./transcript-lines";
import { captionsFor, textRuns, wordsByLine } from "./transcript-playback";
import { partAttributes } from "./transcript-selection";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));
// Counted, to tell how much of the transcript a tick of playback renders again.
vi.mock("./transcript-playback", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./transcript-playback")>();
  return {
    ...actual,
    captionsFor: vi.fn(actual.captionsFor),
    textRuns: vi.fn(actual.textRuns),
    wordsByLine: vi.fn(actual.wordsByLine)
  };
});
vi.mock("./transcript-selection", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./transcript-selection")>();
  return { ...actual, partAttributes: vi.fn(actual.partAttributes) };
});
vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});

const SIGN = "POST /api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/";
const WORDS = "GET /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-words/";

const segments = parseSegments([
  {
    segment_index: 0,
    file_index: 0,
    start: 0,
    end: 4,
    speaker: "SPEAKER_00",
    text: "Välkommen Sugary."
  },
  { segment_index: 1, file_index: 0, start: 5, end: 9, speaker: "SPEAKER_00", text: "Hur mår du?" },
  {
    segment_index: 2,
    file_index: 0,
    start: 10,
    end: 14,
    speaker: "SPEAKER_01",
    text: "Tack Sugary, bra."
  },
  {
    segment_index: 3,
    file_index: 0,
    start: 15,
    end: 19,
    speaker: "SPEAKER_01",
    text: "Sugari kommer sen."
  }
]);

// No audio: the lines are read and corrected without a player.
const target: TranscriptTarget = { stepId: "step-1", stepOrder: 1, attemptNo: 1, fileIds: [] };

/** The transcript with corrections saved as the reviewer makes them. */
function Harness({
  saves,
  audio = target,
  lines = segments,
  speakerReview = null,
  initial
}: {
  saves: CorrectionSet[];
  audio?: TranscriptTarget;
  lines?: TranscriptSegment[];
  speakerReview?: TranscriptSpeakerReview | null;
  initial?: CorrectionSet;
}) {
  const [set, setSet] = useState<CorrectionSet>(() => initial ?? correctionSet(null, lines));
  const shown = shownSegments(lines, {
    occurrences: set.occurrences,
    speaker_edits: set.speakerEdits,
    speaker_names: set.names
  });
  return (
    <TranscriptLines
      flowId="flow-1"
      runId="run-1"
      target={audio}
      shown={shown}
      sourceHash="hash-1"
      multiFile={false}
      speakerReview={speakerReview}
      editing={{
        set,
        speakers: knownSpeakers(lines, set.speakerEdits),
        saving: false,
        save: async (next) => {
          saves.push(next);
          setSet(next);
          return null;
        }
      }}
    />
  );
}

function renderLines(audio?: TranscriptTarget) {
  const saves: CorrectionSet[] = [];
  const view = renderInApp(<Harness saves={saves} audio={audio} />);
  const lines = screen.getByRole("list", { name: messages.flow_runs_transcript_lines });
  return { saves, lines, ...view };
}

/** Marks text in the transcript as a pointer would, from one text node to another. */
function mark(start: Node, from: number, end: Node, to: number) {
  const range = document.createRange();
  range.setStart(start, from);
  range.setEnd(end, to);
  const selection = document.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  act(() => {
    document.dispatchEvent(new Event("selectionchange"));
  });
}

/** Opens a speaker badge's menu and answers it. */
function openMenu(trigger: HTMLElement): HTMLElement {
  expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  fireEvent.click(trigger);
  return document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
}

afterEach(() => {
  cleanup();
  document.getSelection()?.removeAllRanges();
  state.routes = {};
  state.stub.calls.length = 0;
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("TranscriptLines", () => {
  it("shows each speaker as a named badge, never by colour alone", () => {
    const { lines } = renderLines();
    expect(within(lines).getAllByText("SPEAKER_00")).toHaveLength(2);
    expect(within(lines).getAllByText("SPEAKER_01")).toHaveLength(2);
    expect(
      within(lines)
        .getAllByText("SPEAKER_00")[0]!
        .closest("[data-color]")
        ?.getAttribute("data-color")
    ).toBe("blue");
  });

  it("offers the same correction where the transcript likely says it too", async () => {
    const { saves, lines } = renderLines();
    fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 0:00" }));
    fireEvent.change(within(lines).getByLabelText("Texten på raden 0:00"), {
      target: { value: "Välkommen Çagri." }
    });
    fireEvent.click(
      within(lines).getByRole("button", { name: messages.flow_transcript_line_save })
    );

    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_transcript_suggest_title
    });
    // The exact match is chosen, the close spelling is offered.
    const exact = within(dialog).getByRole("checkbox", { name: "0:10: Tack Sugary, bra." });
    const similar = within(dialog).getByRole("checkbox", { name: "0:15: Sugari kommer sen." });
    expect((exact as HTMLInputElement).checked).toBe(true);
    expect((similar as HTMLInputElement).checked).toBe(false);
    await expectNoAxeViolations(document.body);
    fireEvent.click(similar);
    fireEvent.click(within(dialog).getByRole("button", { name: "Rätta valda (2)" }));

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0]!.occurrences).toEqual([
      { segment_index: 0, char_start: 10, char_end: 16, original: "Sugary", corrected: "Çagri" },
      { segment_index: 2, char_start: 5, char_end: 11, original: "Sugary", corrected: "Çagri" },
      { segment_index: 3, char_start: 0, char_end: 6, original: "Sugari", corrected: "Çagri" }
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(lines).getByText("Tack Çagri, bra.")).toBeTruthy();
    expect(document.activeElement).toBe(
      within(lines).getByRole("button", { name: "Rätta raden 0:00" })
    );
  });

  it("saves only the line when the reviewer wants no more", async () => {
    const { saves, lines } = renderLines();
    fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 0:00" }));
    fireEvent.change(within(lines).getByLabelText("Texten på raden 0:00"), {
      target: { value: "Välkommen Çagri." }
    });
    fireEvent.click(
      within(lines).getByRole("button", { name: messages.flow_transcript_line_save })
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_transcript_suggest_skip })
    );
    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0]!.occurrences).toHaveLength(1);
  });

  it("gives text marked in the transcript to a speaker from the toolbar after it", async () => {
    const { saves, lines } = renderLines();
    const second = within(lines).getByText("Hur mår du?").firstChild!;
    const third = within(lines).getByText("Tack Sugary, bra.").firstChild!;
    mark(second, 4, third, 4);

    const toolbar = await screen.findByRole("toolbar", {
      name: messages.flow_transcript_selection_toolbar
    });
    expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_selection_announce);
    // It shows in the line where the marked text ends.
    expect(toolbar.closest("li")?.textContent).toContain("Tack Sugary, bra.");
    await expectNoAxeViolations(document.body);
    fireEvent.click(within(toolbar).getByRole("button", { name: "SPEAKER_01" }));

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0]!.speakerEdits).toEqual([
      {
        segment_index: 1,
        char_start: 4,
        char_end: 11,
        original: "mår du?",
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_01",
        decision: "confirmed"
      },
      {
        segment_index: 2,
        char_start: 0,
        char_end: 4,
        original: "Tack",
        original_speaker: "SPEAKER_01",
        speaker: "SPEAKER_01",
        decision: "confirmed"
      }
    ]);
    await waitFor(() => expect(screen.queryByRole("toolbar")).toBeNull());
  });

  it("closes the toolbar with Esc and leaves the speakers as they were", async () => {
    const { saves, lines } = renderLines();
    const text = within(lines).getByText("Hur mår du?").firstChild!;
    mark(text, 0, text, 3);
    const toolbar = await screen.findByRole("toolbar");
    fireEvent.keyDown(within(toolbar).getByRole("button", { name: "SPEAKER_00" }), {
      key: "Escape"
    });
    await waitFor(() => expect(screen.queryByRole("toolbar")).toBeNull());
    expect(saves).toHaveLength(0);
  });

  it("reads the transcript as speaker turns", async () => {
    renderLines();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_view_turns }));
    const turns = await screen.findByRole("list", { name: messages.flow_transcript_turns_list });
    const items = within(turns).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]!.textContent).toContain("Välkommen Sugary. Hur mår du?");
    expect(within(turns).queryByRole("button", { name: /^Rätta raden/ })).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("corrects a whole turn as one text, saved on the line it changes", async () => {
    const { saves } = renderLines();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_view_turns }));
    const turns = await screen.findByRole("list", { name: messages.flow_transcript_turns_list });
    fireEvent.click(within(turns).getByRole("button", { name: "Rätta repliken 0:00" }));
    const field = within(turns).getByLabelText<HTMLTextAreaElement>("Texten i repliken 0:00");
    expect(field.value).toBe("Välkommen Sugary. Hur mår du?");
    expect(document.activeElement).toBe(field);
    await expectNoAxeViolations(document.body);
    fireEvent.change(field, { target: { value: "Välkommen Sugary. Hur mår ni?" } });
    fireEvent.click(
      within(turns).getByRole("button", { name: messages.flow_transcript_line_save })
    );
    // A correction of one line is offered for the places that likely say the same.
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_transcript_suggest_title
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_transcript_suggest_skip })
    );

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0]!.occurrences).toEqual([
      { segment_index: 1, char_start: 8, char_end: 10, original: "du", corrected: "ni" }
    ]);
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(turns).getByRole("button", { name: "Rätta repliken 0:00" })
      )
    );
    expect(turns.textContent).toContain("Välkommen Sugary. Hur mår ni?");

    // Reverting the turn takes its corrected lines back to what was said.
    fireEvent.click(within(turns).getByRole("button", { name: "Rätta repliken 0:00" }));
    fireEvent.click(
      within(turns).getByRole("button", { name: messages.flow_transcript_turn_revert })
    );
    await waitFor(() => expect(saves).toHaveLength(2));
    expect(saves[1]!.occurrences).toEqual([]);
  });

  it("changes a line's speaker from its badge, and resets it", async () => {
    const { saves, lines } = renderLines();
    const menu = openMenu(
      within(lines).getByRole("button", { name: "SPEAKER_00, byt talare för raden 0:05" })
    );
    await expectNoAxeViolations(document.body);
    fireEvent.click(within(menu).getByRole("menuitemradio", { name: "SPEAKER_01" }));
    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0]!.speakerEdits).toEqual([
      {
        segment_index: 1,
        char_start: null,
        char_end: null,
        original: null,
        original_speaker: "SPEAKER_00",
        speaker: "SPEAKER_01",
        decision: "confirmed"
      }
    ]);

    const again = openMenu(
      await within(lines).findByRole("button", {
        name: "SPEAKER_01, ändrad från SPEAKER_00, byt talare för raden 0:05"
      })
    );
    fireEvent.click(
      within(again).getByRole("menuitem", { name: messages.flow_transcript_speaker_reset })
    );
    await waitFor(() => expect(saves).toHaveLength(2));
    expect(saves[1]!.speakerEdits).toEqual([]);
  });

  it("leaves a whole turn to someone to check from its badge", async () => {
    const { saves } = renderLines();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_view_turns }));
    const turns = await screen.findByRole("list", { name: messages.flow_transcript_turns_list });
    const menu = openMenu(
      within(turns).getByRole("button", { name: "SPEAKER_01, byt talare för repliken 0:10" })
    );
    fireEvent.click(
      within(menu).getByRole("menuitemradio", {
        name: messages.flow_runs_transcript_unknown_speaker
      })
    );
    await waitFor(() => expect(saves).toHaveLength(1));
    expect(
      saves[0]!.speakerEdits.map((edit) => [edit.segment_index, edit.speaker, edit.decision])
    ).toEqual([
      [2, null, "unresolved"],
      [3, null, "unresolved"]
    ]);
  });

  it("takes the reviewer's latest changes back one at a time", async () => {
    const { saves, lines } = renderLines();
    expect(screen.queryByRole("button", { name: messages.flow_transcript_undo })).toBeNull();
    fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 0:05" }));
    fireEvent.change(within(lines).getByLabelText("Texten på raden 0:05"), {
      target: { value: "Hur mår ni?" }
    });
    fireEvent.click(
      within(lines).getByRole("button", { name: messages.flow_transcript_line_save })
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: messages.flow_transcript_suggest_skip
      })
    );
    await waitFor(() => expect(saves).toHaveLength(1));
    const menu = openMenu(
      within(lines).getByRole("button", { name: "SPEAKER_01, byt talare för raden 0:10" })
    );
    fireEvent.click(within(menu).getByRole("menuitemradio", { name: "SPEAKER_00" }));
    await waitFor(() => expect(saves).toHaveLength(2));

    fireEvent.click(await screen.findByRole("button", { name: messages.flow_transcript_undo }));
    await waitFor(() => expect(saves).toHaveLength(3));
    expect(saves[2]!.speakerEdits).toEqual([]);
    expect(saves[2]!.occurrences).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_undo }));
    await waitFor(() => expect(saves).toHaveLength(4));
    expect(saves[3]!.occurrences).toEqual([]);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: messages.flow_transcript_undo })).toBeNull()
    );
  });

  it("keeps the suggested speakers on every line to check at once", async () => {
    const unsure = parseSegments([
      {
        segment_index: 0,
        file_index: 0,
        start: 0,
        end: 4,
        speaker: "SPEAKER_00",
        text: "Ja, precis.",
        overlap_ids: ["audio-1:o1"],
        speaker_attribution: "provisional"
      },
      {
        segment_index: 1,
        file_index: 0,
        start: 2,
        end: 5,
        speaker: "SPEAKER_01",
        text: "Nej, vänta.",
        overlap_ids: ["audio-1:o1"],
        speaker_attribution: "provisional"
      },
      { segment_index: 2, file_index: 0, start: 6, end: 9, speaker: "SPEAKER_00", text: "Okej." }
    ]);
    const saves: CorrectionSet[] = [];
    renderInApp(
      <Harness
        saves={saves}
        lines={unsure}
        speakerReview={{
          files: [
            {
              file_index: 0,
              overlap_detection: "available",
              overlaps: [{ id: "audio-1:o1", start: 1.5, end: 5, detected_speaker_count: 2 }]
            }
          ]
        }}
      />
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Behåll föreslagna talare på alla 2 rader att kontrollera"
      })
    );
    await waitFor(() => expect(saves).toHaveLength(1));
    expect(
      saves[0]!.speakerEdits.map((edit) => [edit.segment_index, edit.speaker, edit.decision])
    ).toEqual([
      [0, "SPEAKER_00", "confirmed"],
      [1, "SPEAKER_01", "confirmed"]
    ]);
    expect(await screen.findByText(messages.flow_transcript_overlap_done)).toBeTruthy();
  });

  it("downloads the reviewed transcript as text", async () => {
    const made: Blob[] = [];
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: (blob: Blob) => {
          made.push(blob);
          return "blob:transcript";
        },
        revokeObjectURL: () => undefined
      })
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderLines();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_export }));
    expect(click).toHaveBeenCalled();
    const text = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsText(made[0]!);
    });
    expect(text).toBe(
      [
        "[00:00:00 - 00:00:04] SPEAKER_00: Välkommen Sugary.",
        "[00:00:05 - 00:00:09] SPEAKER_00: Hur mår du?",
        "[00:00:10 - 00:00:14] SPEAKER_01: Tack Sugary, bra.",
        "[00:00:15 - 00:00:19] SPEAKER_01: Sugari kommer sen.",
        ""
      ].join("\n")
    );
    vi.unstubAllGlobals();
  });
});

describe("TranscriptLines with audio", () => {
  const audioTarget: TranscriptTarget = { ...target, fileIds: ["audio-1"] };

  function answerAudio() {
    state.routes[SIGN] = () => ({
      body: {
        url: "http://backend:8000/api/v1/files/audio-1/download/?token=t0k3n",
        expires_at: "2026-10-22T10:00:00Z"
      }
    });
    state.routes[WORDS] = () => ({
      body: {
        alignment: "forced",
        created_at: "2026-10-22T09:00:00Z",
        flow_run_id: "run-1",
        step_id: "step-1",
        segments_hash: "hash-1",
        stale: false,
        segments: [
          {
            segment_index: 1,
            words: [
              { word: "Hur", start: 5.1, end: 5.4, probability: 0.9 },
              { word: "mår", start: 5.4, end: 5.8, probability: 0 },
              { word: "du?", start: 5.8, end: 6.2, probability: 0.8 }
            ]
          }
        ]
      }
    });
  }

  async function startAudio(lines: HTMLElement) {
    fireEvent.click(within(lines).getByRole("button", { name: /^Spela från 0:05/ }));
    const audio = await screen.findByLabelText<HTMLAudioElement>(
      messages.flow_transcript_audio_label
    );
    fireEvent.loadedMetadata(audio);
    return audio;
  }

  it("counts and marks the words whose time the aligner only guessed", async () => {
    answerAudio();
    const { lines } = renderLines(audioTarget);
    expect(
      await screen.findByText("Ett ord har en osäker tidsstämpel och är vågigt understruket.")
    ).toBeTruthy();
    expect(within(lines).getByText("mår").className).toContain("decoration-wavy");
    expect(within(lines).getByText("Hur").className).not.toContain("decoration-wavy");
  });

  it("reads the word timings of another attempt, after one that had none, where the person is", async () => {
    answerAudio();
    const timed = state.routes[WORDS]!;
    state.routes[WORDS] = () => ({ status: 404, body: { detail: "No word timings" } });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const { lines, rerender } = renderLines(audioTarget);
    const audio = await startAudio(lines);
    const wordReads = () =>
      state.stub.calls.filter((call) => call.path.endsWith("/transcript-words/"));
    await waitFor(() => expect(wordReads()).toHaveLength(1));
    expect(lines.querySelector("[data-word]")).toBeNull();
    Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 5.5 });
    const focused = document.activeElement;
    state.announce.mockClear();

    // The step ran again: its new attempt has word timings.
    state.routes[WORDS] = timed;
    rerender(<Harness saves={[]} audio={{ ...audioTarget, attemptNo: 2 }} />);
    await waitFor(() => expect(wordReads()).toHaveLength(2));
    await waitFor(() => expect(lines.querySelector("[data-word]")).not.toBeNull());
    expect(screen.getByLabelText(messages.flow_transcript_audio_label)).toBe(audio);
    expect(audio.currentTime).toBe(5.5);
    expect(document.activeElement).toBe(focused);
    expect(state.announce).not.toHaveBeenCalled();
  });

  it("plays a speaker's sample and stops after it", async () => {
    answerAudio();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    renderLines(audioTarget);
    fireEvent.click(screen.getByRole("button", { name: "Lyssna på SPEAKER_01" }));
    const audio = await screen.findByLabelText<HTMLAudioElement>(
      messages.flow_transcript_audio_label
    );
    fireEvent.loadedMetadata(audio);
    expect(audio.currentTime).toBe(9.5);
    expect(play).toHaveBeenCalled();

    Object.defineProperty(audio, "currentTime", {
      configurable: true,
      writable: true,
      value: 14.6
    });
    fireEvent.timeUpdate(audio);
    expect(pause).toHaveBeenCalledTimes(1);
  });

  it("skips five seconds either way and moves between the recording's parts", async () => {
    answerAudio();
    // Each part's link is its own file's.
    state.routes[SIGN] = (init: { params: { path: { file_id: string } } }) => ({
      body: {
        url: `http://backend:8000/api/v1/files/${init.params.path.file_id}/download/?token=t0k3n`,
        expires_at: Math.floor(Date.now() / 1000) + 3_600
      }
    });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    const { lines } = renderLines({ ...target, fileIds: ["audio-1", "audio-2"] });
    fireEvent.click(within(lines).getByRole("button", { name: /^Spela från 0:05/ }));
    const audio = await screen.findByLabelText<HTMLAudioElement>(
      "Ljudet till transkriptionen, del 1"
    );
    fireEvent.loadedMetadata(audio);
    Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 30 });
    fireEvent.click(screen.getByRole("button", { name: "5 sekunder framåt" }));
    expect(audio.currentTime).toBe(35);
    fireEvent.click(screen.getByRole("button", { name: "5 sekunder bakåt" }));
    fireEvent.click(screen.getByRole("button", { name: "5 sekunder bakåt" }));
    expect(audio.currentTime).toBe(25);
    const previous = screen.getByRole("button", {
      name: messages.flow_transcript_audio_previous_part
    });
    expect(
      previous.getAttribute("aria-disabled") === "true" || (previous as HTMLButtonElement).disabled
    ).toBe(true);
    await expectNoAxeViolations(document.body);

    // Paused, the next part loads from its start without playing.
    Object.defineProperty(audio, "paused", { configurable: true, value: true });
    play.mockClear();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_audio_next_part }));
    const second = await screen.findByLabelText<HTMLAudioElement>(
      "Ljudet till transkriptionen, del 2"
    );
    const signed = state.stub.calls
      .filter((call) => call.path.endsWith("/signed-url/"))
      .map((call) => (call.init as { params: { path: { file_id: string } } }).params.path.file_id);
    expect(signed).toEqual(["audio-1", "audio-2"]);
    fireEvent.loadedMetadata(second);
    expect(second.currentTime).toBe(0);
    expect(play).not.toHaveBeenCalled();
  });

  it("signs the audio link again a minute before it runs out, where the person is", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"], shouldAdvanceTime: true });
    try {
      answerAudio();
      const expires = Math.floor(Date.now() / 1000) + 3_600;
      const sign = state.routes[SIGN]!;
      state.routes[SIGN] = (init) => ({
        body: { ...(sign(init).body as object), expires_at: expires }
      });
      const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
      vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
      const { lines } = renderLines(audioTarget);
      const audio = await startAudio(lines);
      Object.defineProperty(audio, "currentTime", {
        configurable: true,
        writable: true,
        value: 42
      });
      Object.defineProperty(audio, "paused", { configurable: true, value: true });
      play.mockClear();
      const signs = () => state.stub.calls.filter((call) => call.path.endsWith("/signed-url/"));
      expect(signs()).toHaveLength(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3_600_000 - 60_000 - 1_000);
      });
      expect(signs()).toHaveLength(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      await waitFor(() => expect(signs()).toHaveLength(2));
      fireEvent.loadedMetadata(audio);
      expect(audio.currentTime).toBe(42);
      expect(play).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("changes the speed, and skips with J, K and L only while the player has focus", async () => {
    answerAudio();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    const { lines } = renderLines(audioTarget);
    const audio = await startAudio(lines);
    const player = screen.getByRole("group", { name: messages.flow_transcript_player_label });
    expect(player.getAttribute("aria-describedby")).toBeTruthy();
    expect(
      document.getElementById(player.getAttribute("aria-describedby")!)?.textContent
    ).toContain("spela eller pausa");
    await expectNoAxeViolations(document.body);

    Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 30 });
    fireEvent.keyDown(window, { key: "l" });
    expect(audio.currentTime).toBe(30);

    // Focus anywhere in the player: here its speed control (jsdom cannot focus the audio element).
    act(() => screen.getByRole("combobox", { name: messages.flow_transcript_audio_rate }).focus());
    fireEvent.keyDown(window, { key: "l" });
    expect(audio.currentTime).toBe(40);
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "j" });
    expect(audio.currentTime).toBe(20);
    play.mockClear();
    fireEvent.keyDown(window, { key: "k" });
    expect(play).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("combobox", { name: messages.flow_transcript_audio_rate }));
    fireEvent.click(await screen.findByRole("option", { name: "1,5×" }));
    expect(audio.playbackRate).toBe(1.5);
  });
});

// Five hundred lines take seconds to render in jsdom.
describe("TranscriptLines with audio, a long transcript", { timeout: 30_000 }, () => {
  const COUNT = 500;
  // Line n plays from 4n s for 3 s, four words of 0.75 s each, then a second of silence.
  const long = parseSegments(
    Array.from({ length: COUNT }, (_, n) => ({
      segment_index: n,
      file_index: 0,
      start: n * 4,
      end: n * 4 + 3,
      speaker: n % 7 < 3 ? "SPEAKER_00" : "SPEAKER_01",
      text: `ord${n} ett två tre`
    }))
  );
  // Line 3 is corrected: its words are placed in raw text it no longer shows.
  const corrected: CorrectionSet = {
    ...correctionSet(null, long),
    occurrences: [
      { segment_index: 3, char_start: 5, char_end: 8, original: "ett", corrected: "Ett" }
    ]
  };
  const audioTarget: TranscriptTarget = { ...target, fileIds: ["audio-1"] };

  function answerLongAudio() {
    state.routes[SIGN] = () => ({
      body: {
        url: "http://backend:8000/api/v1/files/audio-1/download/?token=t0k3n",
        expires_at: "2026-10-22T10:00:00Z"
      }
    });
    state.routes[WORDS] = () => ({
      body: {
        alignment: "provider_words",
        created_at: "2026-10-22T09:00:00Z",
        flow_run_id: "run-1",
        step_id: "step-1",
        segments_hash: "hash-1",
        stale: false,
        // Line 2 has no word timings.
        segments: long
          .filter((line) => line.index !== 2)
          .map((line) => ({
            segment_index: line.index,
            words: line.text.split(" ").map((word, at) => ({
              word,
              start: line.start + at * 0.75,
              end: line.start + (at + 1) * 0.75,
              probability: 0.9
            }))
          }))
      }
    });
  }

  async function startLong(list: HTMLElement) {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    fireEvent.click(within(item(list, 0)).getByRole("button", { name: /^Spela från 0:00/ }));
    // Found directly: a label query over five hundred lines takes seconds in jsdom.
    const audio = await waitFor(() => {
      const element = document.querySelector("audio");
      expect(element).not.toBeNull();
      return element!;
    });
    fireEvent.loadedMetadata(audio);
    await waitFor(() => expect(item(list, 0).querySelector("[data-word]")).not.toBeNull());
    // Playing, so the list follows.
    Object.defineProperty(audio, "paused", { configurable: true, value: false });
    return audio;
  }

  function item(list: HTMLElement, position: number): HTMLElement {
    return list.children[position] as HTMLElement;
  }

  function playAt(audio: HTMLAudioElement, time: number) {
    Object.defineProperty(audio, "currentTime", {
      configurable: true,
      writable: true,
      value: time
    });
    fireEvent.timeUpdate(audio);
  }

  /** The one item marked playing, and the one word marked in it (null for none). */
  function expectPlaying(list: HTMLElement, position: number, word: number | null) {
    const current = list.querySelectorAll('[aria-current="time"]');
    expect(current).toHaveLength(1);
    const playing = item(list, position);
    expect(playing.contains(current[0]!)).toBe(true);
    expect([...list.querySelectorAll(":scope > li.bg-ax-selected")]).toEqual([playing]);
    const marked = [...list.querySelectorAll(".bg-ax-accent-muted")];
    expect(marked).toEqual(word === null ? [] : [playing.querySelector(`[data-word="${word}"]`)]);
  }

  it("moves the line and word marks as it plays, rendering again only the lines they leave and reach", async () => {
    answerLongAudio();
    renderInApp(<Harness saves={[]} audio={audioTarget} lines={long} initial={corrected} />);
    const list = screen.getByRole("list", { name: messages.flow_runs_transcript_lines });
    const audio = await startLong(list);
    expect(list.querySelectorAll('[aria-current="time"]')).toHaveLength(0);
    const scrolled: Element[] = [];
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(function (this: Element) {
      scrolled.push(this);
    });
    vi.mocked(textRuns).mockClear();
    vi.mocked(wordsByLine).mockClear();
    vi.mocked(captionsFor).mockClear();

    // [time, line, word marked]: twenty word changes, within lines, across them, by a seek
    // forward and back, through a line without word timings and a corrected one.
    const ticks: [number, number, number | null][] = [
      [0, 0, 0],
      [0.8, 0, 1],
      [1.6, 0, 2],
      [2.3, 0, 3],
      [4, 1, 0],
      [4.8, 1, 1],
      [8.1, 2, null],
      [12, 3, null],
      [12.8, 3, null],
      [16, 4, 0],
      [16.8, 4, 1],
      [17.6, 4, 2],
      [18.3, 4, 3],
      [400, 100, 0],
      [400.8, 100, 1],
      [399.5, 99, 3],
      [1996, 499, 0],
      [1996.8, 499, 1],
      [1997.6, 499, 2],
      [1998.3, 499, 3]
    ];
    const lineChanges: Element[] = [];
    let previous = -1;
    for (const [time, line, word] of ticks) {
      const before = vi.mocked(textRuns).mock.calls.length;
      playAt(audio, time);
      expectPlaying(list, line, word);
      expect(vi.mocked(textRuns).mock.calls.length - before).toBeLessThanOrEqual(2);
      if (line !== previous) lineChanges.push(item(list, line));
      previous = line;
    }
    // A pause between lines keeps the earlier one, and renders nothing.
    const before = vi.mocked(textRuns).mock.calls.length;
    playAt(audio, 1999.5);
    expectPlaying(list, 499, 3);
    expect(vi.mocked(textRuns).mock.calls.length).toBe(before);

    // The list followed each new line, never a word.
    expect(scrolled).toEqual(lineChanges);
    // The words and the captions were worked out once, not on each tick.
    expect(wordsByLine).not.toHaveBeenCalled();
    expect(captionsFor).not.toHaveBeenCalled();
  });

  it("marks the turn and the line in it that plays, rendering again only the turns they leave and reach", async () => {
    answerLongAudio();
    renderInApp(<Harness saves={[]} audio={audioTarget} lines={long} />);
    const lines = screen.getByRole("list", { name: messages.flow_runs_transcript_lines });
    const audio = await startLong(lines);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_view_turns }));
    const turns = screen.getByRole("list", { name: messages.flow_transcript_turns_list });
    vi.mocked(partAttributes).mockClear();

    /** The turn a line is in: speakers change after lines 3, 7, 10, 14, … (n % 7 < 3). */
    const turnOf = (line: number) => Math.floor(line / 7) * 2 + (line % 7 < 3 ? 0 : 1);
    const ticks: [number, number][] = [
      [0, 0],
      [0.8, 0],
      [4, 1],
      [8, 2],
      [12, 3],
      [12.8, 3],
      [16, 4],
      [400, 100],
      [1996, 499]
    ];
    for (const [time, line] of ticks) {
      const before = vi.mocked(partAttributes).mock.calls.length;
      playAt(audio, time);
      const current = turns.querySelectorAll('[aria-current="time"]');
      expect(current).toHaveLength(1);
      const turn = item(turns, turnOf(line));
      expect(turn.contains(current[0]!)).toBe(true);
      expect([...turns.querySelectorAll(":scope > li.bg-ax-selected")]).toEqual([turn]);
      const marked = [...turns.querySelectorAll(".bg-ax-accent-muted")];
      expect(marked).toHaveLength(1);
      expect(marked[0]!.textContent).toBe(`ord${line} ett två tre`);
      // A turn holds at most four lines: the turn left and the turn reached render.
      expect(vi.mocked(partAttributes).mock.calls.length - before).toBeLessThanOrEqual(8);
    }
  });

  it("marks the line playing in the part of the recording that plays", async () => {
    const parts = parseSegments([
      {
        segment_index: 0,
        file_index: 0,
        start: 0,
        end: 3,
        speaker: "SPEAKER_00",
        text: "Del ett."
      },
      { segment_index: 1, file_index: 1, start: 0, end: 3, speaker: "SPEAKER_00", text: "Del två." }
    ]);
    state.routes[SIGN] = (init: { params: { path: { file_id: string } } }) => ({
      body: {
        url: `http://backend:8000/api/v1/files/${init.params.path.file_id}/download/?token=t0k3n`,
        expires_at: "2026-10-22T10:00:00Z"
      }
    });
    // Words written for another transcript are not used: the lines are marked whole.
    state.routes[WORDS] = () => ({
      body: {
        alignment: "provider_words",
        created_at: "2026-10-22T09:00:00Z",
        flow_run_id: "run-1",
        step_id: "step-1",
        segments_hash: "hash-1",
        stale: true,
        segments: [{ segment_index: 1, words: [{ word: "Del", start: 0, end: 1, probability: 1 }] }]
      }
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    renderInApp(
      <Harness saves={[]} audio={{ ...target, fileIds: ["audio-1", "audio-2"] }} lines={parts} />
    );
    const list = screen.getByRole("list", { name: messages.flow_runs_transcript_lines });
    fireEvent.click(within(item(list, 1)).getByRole("button", { name: /^Spela från/ }));
    const audio = await screen.findByLabelText<HTMLAudioElement>(
      "Ljudet till transkriptionen, del 2"
    );
    fireEvent.loadedMetadata(audio);
    playAt(audio, 0.5);
    expectPlaying(list, 1, null);
    expect(list.querySelector("[data-word]")).toBeNull();
  });
});
