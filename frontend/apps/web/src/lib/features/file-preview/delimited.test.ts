import { describe, expect, it } from "vitest";
import { parseDelimited, sniffDelimiter } from "./delimited";

describe("parseDelimited", () => {
  it("keeps delimiters, line breaks and doubled quotes inside quoted fields", () => {
    expect(parseDelimited('name,note\r\n"Berg, Anna","said ""hi""\nthen left"\n')).toEqual([
      ["name", "note"],
      ["Berg, Anna", 'said "hi"\nthen left']
    ]);
  });

  it("keeps empty fields and skips blank lines", () => {
    expect(parseDelimited('a,,c\n\n"",2,\n')).toEqual([
      ["a", "", "c"],
      ["", "2", ""]
    ]);
  });

  it("reads the delimiter from the first record", () => {
    expect(parseDelimited("namn;belopp\nAnna;1,5\n")).toEqual([
      ["namn", "belopp"],
      ["Anna", "1,5"]
    ]);
    expect(sniffDelimiter('"a,b,c";d\n1,2,3,4')).toBe(";");
    expect(sniffDelimiter("a\tb\n")).toBe("\t");
    expect(sniffDelimiter("single")).toBe(",");
  });
});
