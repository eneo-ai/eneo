// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { LongMaterialCoverage as Coverage } from "./long-material";
import { LongMaterialCoverage } from "./long-material-coverage";

afterEach(cleanup);

const partial: Coverage = {
  mode: "digest",
  coverage: "partial",
  reasons: ["deadline", "something new"],
  left_out: ["S2"],
  sources: [
    {
      key: "S1",
      index: 1,
      title: "Avtal.pdf",
      reference: { kind: "file" },
      start_char: 0,
      end_char: 100,
      segments_planned: 2,
      segments_read: [1, 2],
      complete: true
    },
    {
      key: "S2",
      index: 2,
      title: "Bilaga.pdf",
      reference: { kind: "file" },
      start_char: 100,
      end_char: 400,
      segments_planned: 6,
      segments_read: [1, 2],
      segments_not_read: [3, 4, 5, 6],
      complete: false
    }
  ],
  input_tokens_estimate: 90_000,
  segment_tokens: 12_000,
  reduce_input_tokens: 60_000,
  reduce_levels: 1,
  map_calls: 4,
  reduce_calls: 1,
  failed_calls: 0
};

describe("LongMaterialCoverage", () => {
  it("says what a partial read covered, why and what it left out", async () => {
    const { container } = renderInApp(<LongMaterialCoverage coverage={partial} />);
    expect(screen.getByText("Delvis läst")).toBeTruthy();
    expect(screen.getByText("4 av 8 delar från 2 källor")).toBeTruthy();
    expect(screen.getByText("Ett samlat svar utifrån delarnas anteckningar")).toBeTruthy();
    expect(screen.getByText("5 anrop till modellen, 0 misslyckades")).toBeTruthy();
    expect(screen.getByText("tiden tog slut, something new")).toBeTruthy();
    expect(screen.getByText("Bilaga.pdf: del 3-6 av 6")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("names no result for a read that was cancelled", () => {
    renderInApp(<LongMaterialCoverage coverage={{ ...partial, coverage: "cancelled" }} />);
    expect(screen.getByText("Avbruten")).toBeTruthy();
    expect(screen.queryByText("Ett samlat svar utifrån delarnas anteckningar")).toBeNull();
  });
});
