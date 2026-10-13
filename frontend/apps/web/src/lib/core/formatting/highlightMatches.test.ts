import { describe, expect, it } from "vitest";
import { splitMatches } from "./highlightMatches";

describe("splitMatches", () => {
  it("marks every case-insensitive occurrence in order", () => {
    expect(splitMatches("Larm – larmlista", "larm")).toEqual([
      { text: "Larm", match: true },
      { text: " – ", match: false },
      { text: "larm", match: true },
      { text: "lista", match: false }
    ]);
  });

  it("returns the text untouched without a query or a hit", () => {
    expect(splitMatches("Policy", "")).toEqual([{ text: "Policy", match: false }]);
    expect(splitMatches("Policy", "larm")).toEqual([{ text: "Policy", match: false }]);
  });
});
