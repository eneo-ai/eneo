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

const state = vi.hoisted(() => ({ announce: vi.fn() }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

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
function Harness({ saves }: { saves: CorrectionSet[] }) {
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
      target={target}
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

function renderLines() {
  const saves: CorrectionSet[] = [];
  const view = renderInApp(<Harness saves={saves} />);
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

afterEach(() => {
  cleanup();
  document.getSelection()?.removeAllRanges();
  vi.clearAllMocks();
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
});
