import { describe, expect, it } from "vitest";
import {
  composeQuotedQuestion,
  parseQuotedQuestion,
  quotedFileMatches,
  tableQuoteSummary
} from "./question-quote";

const fileId = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b";

describe("question quotes", () => {
  it("puts the quote and its file before the question", () => {
    expect(
      composeQuotedQuestion({ text: "One\n\nTwo", fileName: "a.md", locator: null }, "Why?")
    ).toBe("> One\n>\n> Two\n> (a.md)\n\nWhy?");
  });

  it("reads back what it composed, with the exact file and where the passage stands", () => {
    const sent = composeQuotedQuestion(
      { text: "Same line", fileName: "notes, v2.md", fileId, locator: "occurrence 2 of 5" },
      "Shorter?"
    );
    expect(parseQuotedQuestion(sent)).toEqual({
      quote: {
        text: "Same line",
        fileName: "notes, v2.md",
        fileId,
        locator: "occurrence 2 of 5"
      },
      text: "Shorter?"
    });
  });

  it("reads a quote typed by hand, without a file", () => {
    expect(parseQuotedQuestion("> Just this\n\nOk?")).toEqual({
      quote: { text: "Just this", fileName: null, locator: null },
      text: "Ok?"
    });
  });

  it("leaves text that only starts with a quote mark alone", () => {
    expect(parseQuotedQuestion("> not a paragraph\nnext line")).toEqual({
      quote: null,
      text: "> not a paragraph\nnext line"
    });
  });

  it("matches an exact file by id and a legacy quote by name only", () => {
    expect(
      quotedFileMatches(
        { text: "", fileName: "a.md", fileId, locator: null },
        { id: fileId, name: "b.md" }
      )
    ).toBe(true);
    expect(
      quotedFileMatches(
        { text: "", fileName: "a.md", fileId, locator: null },
        { id: "other", name: "a.md" }
      )
    ).toBe(false);
    expect(
      quotedFileMatches(
        { text: "", fileName: "a.md", locator: null },
        { id: "other", name: "a.md" }
      )
    ).toBe(true);
  });
});

it("sums up a table quote as its columns and row count", () => {
  expect(tableQuoteSummary("| Fas | Innehåll |\n| --- | --- |\n| A | b |\n| C | d |")).toEqual({
    columns: ["Fas", "Innehåll"],
    rows: 2
  });
  expect(tableQuoteSummary("Bara text")).toBeNull();
});
