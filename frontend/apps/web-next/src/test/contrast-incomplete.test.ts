import { describe, expect, it } from "vitest";
import type { Result } from "axe-core";
import { incompleteCounts } from "../../tests/contrast-incomplete";

const scan = (nodes: { target: string[]; reason: string }[]) =>
  [
    {
      id: "color-contrast",
      nodes: nodes.map(({ target, reason }) => ({
        target,
        any: [{ data: { messageKey: reason } }]
      }))
    }
  ] as unknown as Result[];

describe("incompleteCounts", () => {
  it("counts each place once, however many rows repeat it", () => {
    const rows = Array.from({ length: 40 }, (_, row) => ({
      target: [`table > tbody > tr:nth-child(${row + 1}) > td:nth-child(3) > span`],
      reason: "pseudoContent"
    }));
    expect(incompleteCounts(scan(rows))).toEqual({ pseudoContent: 1 });
  });

  it("counts a place once whatever ids or attributes tell its copies apart", () => {
    // Rows of links differ by their href and a generated id, not by where they are.
    const chips = [0, 1, 2].map((index) => ({
      target: [`nav > a#space-${index}.astryx-side-nav-item[href="/s/${index}"] > span.chip`],
      reason: "bgOverlap"
    }));
    expect(incompleteCounts(scan(chips))).toEqual({ bgOverlap: 1 });
  });

  it("counts another column, component or named control as a place of its own", () => {
    expect(
      incompleteCounts(
        scan([
          { target: ["tr:nth-child(1) > td:nth-child(2) > span"], reason: "pseudoContent" },
          { target: ["tr:nth-child(2) > td:nth-child(3) > span"], reason: "pseudoContent" },
          { target: ["div > .astryx-button-label"], reason: "bgOverlap" },
          { target: ["div > .astryx-side-nav-item-label"], reason: "bgOverlap" },
          { target: ["#assistant-description"], reason: "bgGradient" },
          { target: ["#assistant-prompt"], reason: "bgGradient" },
          { target: ['[data-section="general"] > p'], reason: "bgImage" },
          { target: ['[data-section="prompt"] > p'], reason: "bgImage" },
          // The file preview's table: its columns are numbered, its rows repeat.
          { target: ['tr[data-row="2"] > td[data-column="0"]'], reason: "elmPartiallyObscured" },
          { target: ['tr[data-row="2"] > td[data-column="1"]'], reason: "elmPartiallyObscured" },
          { target: ['tr[data-row="3"] > td[data-column="1"]'], reason: "elmPartiallyObscured" }
        ])
      )
    ).toEqual({
      pseudoContent: 2,
      bgOverlap: 2,
      bgGradient: 2,
      bgImage: 2,
      elmPartiallyObscured: 2
    });
  });

  it("keeps different places and reasons apart", () => {
    expect(
      incompleteCounts(
        scan([
          { target: ["td:nth-child(2) > span"], reason: "pseudoContent" },
          { target: ["td:nth-child(3) > button"], reason: "pseudoContent" },
          { target: ["header > a"], reason: "bgOverlap" }
        ])
      )
    ).toEqual({ pseudoContent: 2, bgOverlap: 1 });
  });
});
