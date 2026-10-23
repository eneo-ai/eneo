import { describe, expect, it } from "vitest";
import { readPartialArguments, readPartialStringArguments } from "./partialToolArguments";

describe("partial tool arguments", () => {
  it("reads finished values and the unfinished one as far as it goes", () => {
    expect(
      readPartialStringArguments(
        '{"title":"Införandeplan","format":"md","content":"# Plan\\n\\nFas'
      )
    ).toEqual({ title: "Införandeplan", format: "md", content: "# Plan\n\nFas" });
  });

  it("reads the same values from the complete object", () => {
    const whole = JSON.stringify({ title: 'En "plan"', content: "a\tb\\c/då" });
    expect(readPartialStringArguments(whole)).toEqual(JSON.parse(whole));
  });

  it("leaves out an escape that is cut in half", () => {
    expect(readPartialStringArguments('{"content":"rad\\')).toEqual({ content: "rad" });
    expect(readPartialStringArguments('{"content":"rad\\u00e')).toEqual({ content: "rad" });
    expect(readPartialStringArguments('{"content":"rad\\u00e5')).toEqual({ content: "radå" });
  });

  it("waits for the second half of a surrogate pair", () => {
    expect(readPartialStringArguments('{"content":"ok \\ud83d')).toEqual({ content: "ok " });
    expect(readPartialStringArguments('{"content":"ok \\ud83d\\ude00')).toEqual({
      content: "ok 😀"
    });
  });

  it("skips values that are not strings", () => {
    expect(
      readPartialStringArguments(
        '{"revises":{"url":"https://x/y","filename":"a}b.md"},"pages":[1,2],"draft":true,"title":"T'
      )
    ).toEqual({ title: "T" });
  });

  it("returns what it has when the text stops between values", () => {
    expect(readPartialStringArguments("")).toEqual({});
    expect(readPartialStringArguments('{"tit')).toEqual({});
    expect(readPartialStringArguments('{"title":')).toEqual({});
    expect(readPartialStringArguments('{"title":"T","revises":{"url":"htt')).toEqual({
      title: "T"
    });
  });
});

describe("readPartialArguments", () => {
  it("keeps nested values as far as they are written", () => {
    expect(
      readPartialArguments('{"title":"Plan","sheets":[{"name":"Budget","rows":[[1,2],[3,')
    ).toEqual({ title: "Plan", sheets: [{ name: "Budget", rows: [[1, 2], [3]] }] });
  });

  it("keeps a string that is cut and leaves out a number that may still grow", () => {
    expect(readPartialArguments('{"city":"Sunds')).toEqual({ city: "Sunds" });
    expect(readPartialArguments('{"city":"Sundsvall","days":1')).toEqual({ city: "Sundsvall" });
    expect(readPartialArguments('{"city":"Sundsvall","days":14,')).toEqual({
      city: "Sundsvall",
      days: 14
    });
  });

  it("leaves out a key whose value has not started", () => {
    expect(readPartialArguments('{"a":true,"b":')).toEqual({ a: true });
    expect(readPartialArguments('{"a":true,"b')).toEqual({ a: true });
  });

  it("reads finished arguments as JSON does", () => {
    const args = { title: "Plan", nested: { list: [1, "två", null, false], n: -1.5 } };
    expect(readPartialArguments(JSON.stringify(args))).toEqual(args);
  });

  it("gives an empty object for anything that is not an object", () => {
    expect(readPartialArguments("")).toEqual({});
    expect(readPartialArguments("[1,2")).toEqual({});
  });
});
