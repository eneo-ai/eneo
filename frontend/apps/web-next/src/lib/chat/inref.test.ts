import { describe, expect, it } from "vitest";
import { resolveInrefs, stripInrefs, trimPartialInref } from "./inref";

const SOURCES = ["a5477f85-1111-4111-8111-111111111111", "b3291cc0-2222-4222-8222-222222222222"];

describe("resolveInrefs", () => {
  it("rewrites tags to 1-based [N] markers by id prefix", () => {
    expect(resolveInrefs('Fakta.<inref id="b3291cc0"/> Mer.<inref id="a5477f85"/>', SOURCES)).toBe(
      "Fakta.[2] Mer.[1]"
    );
  });

  it("drops tags that match no source", () => {
    expect(resolveInrefs('Fakta.<inref id="deadbeef"/>', SOURCES)).toBe("Fakta.");
  });

  it("tolerates spacing and paired-close variants", () => {
    expect(
      resolveInrefs('X <inref id="a5477f85" /> Y <inref id="b3291cc0"></inref>', SOURCES)
    ).toBe("X [1] Y [2]");
  });

  it("leaves text without tags untouched", () => {
    const text = "5 < 6 and [1] stays";
    expect(resolveInrefs(text, SOURCES)).toBe(text);
  });
});

describe("stripInrefs", () => {
  it("removes tags without replacement", () => {
    expect(stripInrefs('Fakta.<inref id="a5477f85"/> Mer.')).toBe("Fakta. Mer.");
  });
});

describe("trimPartialInref", () => {
  it("hides an incomplete trailing tag", () => {
    expect(trimPartialInref("Svar <in")).toBe("Svar ");
    expect(trimPartialInref('Svar <inref id="a54')).toBe("Svar ");
  });

  it("keeps complete tags and ordinary angle brackets", () => {
    expect(trimPartialInref('Svar <inref id="a5477f85"/>')).toBe('Svar <inref id="a5477f85"/>');
    expect(trimPartialInref("5 < 6")).toBe("5 < 6");
  });
});
