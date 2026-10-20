// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowTranscript, formatClock, transcriptTurns } from "./flow-transcript";

const segments = [
  { file_index: 0, start: 0, end: 4.5, speaker: "SPEAKER_00", text: "Hej Anna." },
  { file_index: 0, start: 4.5, end: 9, speaker: "SPEAKER_00", text: "Vi börjar." },
  { file_index: 0, start: 9, end: 12, speaker: "SPEAKER_01", text: "Hej." },
  { file_index: 1, start: 0, end: 3, speaker: "SPEAKER_01", text: "Andra filen." }
];

afterEach(cleanup);

describe("transcript turns", () => {
  it("folds consecutive segments of one speaker within a file", () => {
    expect(transcriptTurns(segments).map((turn) => [turn.speaker, turn.lines.length])).toEqual([
      ["SPEAKER_00", 2],
      ["SPEAKER_01", 1],
      ["SPEAKER_01", 1]
    ]);
    expect(formatClock(3725.9)).toBe("01:02:05");
  });
});

describe("FlowTranscript", () => {
  it("shows named turns with their windows", async () => {
    const { container } = renderInApp(
      <FlowTranscript
        transcription={{ segments, speaker_names: { SPEAKER_00: "Anna", SPEAKER_01: null } }}
      />
    );
    const list = screen.getByRole("list", { name: "Transkript" });
    const turns = within(list).getAllByRole("listitem");
    expect(turns).toHaveLength(3);
    expect(turns[0]!.textContent).toContain("00:00:00 – 00:00:09");
    expect(turns[0]!.textContent).toContain("Anna");
    expect(turns[0]!.textContent).toContain("Hej Anna. Vi börjar.");
    expect(turns[1]!.textContent).toContain("SPEAKER_01");
    await expectNoAxeViolations(container);
  });

  it("says when there is nothing", () => {
    renderInApp(<FlowTranscript transcription={{ segments: [] }} />);
    expect(screen.getByText("Transkriptet är tomt.")).toBeTruthy();
  });
});
