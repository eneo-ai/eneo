import { describe, expect, it } from "vitest";
import { citedSourceIndices, resolveInrefs, stripInrefs, trimPartialInref } from "./inref";

const SOURCES = ["a5477f85-1111-4111-8111-111111111111", "b3291cc0-2222-4222-8222-222222222222"];

describe("resolveInrefs", () => {
  it("rewrites tags to private 1-based markers by id prefix", () => {
    expect(resolveInrefs('Fakta.<inref id="b3291cc0"/> Mer.<inref id="a5477f85"/>', SOURCES)).toBe(
      "Fakta.\uE0002\uE001 Mer.\uE0001\uE001"
    );
  });

  it("drops tags that match no source", () => {
    expect(resolveInrefs('Fakta.<inref id="deadbeef"/>', SOURCES)).toBe("Fakta.");
  });

  it("tolerates spacing and paired-close variants", () => {
    expect(
      resolveInrefs('X <inref id="a5477f85" /> Y <inref id="b3291cc0"></inref>', SOURCES)
    ).toBe("X \uE0001\uE001 Y \uE0002\uE001");
  });

  it("leaves text without tags untouched", () => {
    const text = "5 < 6 and [1] stays";
    expect(resolveInrefs(text, SOURCES)).toBe(text);
  });

  it("never converts raw numeric brackets in the model's answer", () => {
    expect(resolveInrefs('Text [1] [3]<inref id="a5477f85"/>', SOURCES)).toBe(
      "Text [1] [3]\uE0001\uE001"
    );
  });

  it("waits for a complete tag before numbering it", () => {
    expect(resolveInrefs('Fakta.<inref id="a5477f85">', SOURCES)).toBe(
      'Fakta.<inref id="a5477f85">'
    );
  });
});

describe("citedSourceIndices", () => {
  it("orders distinct known sources by first complete citation and ignores repeats", () => {
    expect(
      citedSourceIndices(
        'A<inref id="b3291cc0"/> B<inref id="a5477f85"/> C<inref id="b3291cc0"/>',
        SOURCES
      )
    ).toEqual([1, 0]);
  });

  it("ignores incomplete and unknown tags", () => {
    expect(citedSourceIndices('A<inref id="a5477f85"> B<inref id="deadbeef"/>', SOURCES)).toEqual(
      []
    );
  });
});

describe("stripInrefs", () => {
  it("removes tags without replacement", () => {
    expect(stripInrefs('Fakta.<inref id="a5477f85"/> Mer.')).toBe("Fakta. Mer.");
  });

  it("also removes an open tag that is not safe to render as a citation", () => {
    expect(stripInrefs('Fakta.<inref id="a5477f85"> Mer.')).toBe("Fakta. Mer.");
  });
});

describe("trimPartialInref", () => {
  it("hides an incomplete trailing tag", () => {
    expect(trimPartialInref("Svar <in")).toBe("Svar ");
    expect(trimPartialInref('Svar <inref id="a54')).toBe("Svar ");
    expect(trimPartialInref('Svar <inref id="a5477f85">')).toBe("Svar ");
  });

  it("keeps complete tags and ordinary angle brackets", () => {
    expect(trimPartialInref('Svar <inref id="a5477f85"/>')).toBe('Svar <inref id="a5477f85"/>');
    expect(trimPartialInref("5 < 6")).toBe("5 < 6");
  });
});
