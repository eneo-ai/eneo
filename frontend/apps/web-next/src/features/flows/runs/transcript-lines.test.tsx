// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { parseSegments, shownSegments, type TranscriptTarget } from "./transcript";
import { correctionSet, knownSpeakers, type CorrectionSet } from "./transcript-corrections";
import { TranscriptLines } from "./transcript-lines";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));
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
function Harness({ saves, audio = target }: { saves: CorrectionSet[]; audio?: TranscriptTarget }) {
  const [set, setSet] = useState<CorrectionSet>(() => correctionSet(null, segments));
  const shown = shownSegments(segments, {
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
      editing={{
        set,
        speakers: knownSpeakers(segments, set.speakerEdits),
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
