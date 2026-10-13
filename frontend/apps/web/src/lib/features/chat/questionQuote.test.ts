import { describe, expect, it } from "vitest";
import { composeQuotedQuestion, parseQuotedQuestion, quotedFileMatches } from "./questionQuote";

describe("question quotes", () => {
  const quote = {
    text: "Första stycket\n\nAndra stycket",
    fileName: "Skrivelse (v2).docx",
    locator: null
  };

  it("puts the quote and its file before the question", () => {
    expect(composeQuotedQuestion(quote, "Korta ner det här")).toBe(
      "> Första stycket\n>\n> Andra stycket\n> (Skrivelse (v2).docx)\n\nKorta ner det här"
    );
    expect(composeQuotedQuestion(null, "Hej")).toBe("Hej");
  });

  it("reads back what it composed", () => {
    expect(parseQuotedQuestion(composeQuotedQuestion(quote, "Korta ner\ndet här"))).toEqual({
      quote,
      text: "Korta ner\ndet här"
    });
    expect(parseQuotedQuestion(composeQuotedQuestion(quote, ""))).toEqual({ quote, text: "" });
  });

  it("carries where a repeated passage stands, after the file name", () => {
    for (const located of [
      { text: "Personal", fileName: "Budget, utfall.xlsx", locator: "occurrence 2 of 5" },
      {
        text: "Personal",
        fileName: "utfall.xlsx",
        locator: "row 3 (data row 2), cells: Vård (norr), Augusti | Personal | 19072"
      },
      {
        text: "Personal",
        fileName: "utfall.xlsx",
        locator: 'sheet "Utfall, 2025", rows 8-12 (data rows 7-11)'
      }
    ]) {
      const question = composeQuotedQuestion(located, "Ändra");
      expect(question).toContain(`> (${located.fileName}, ${located.locator})`);
      expect(parseQuotedQuestion(question)).toEqual({ quote: located, text: "Ändra" });
    }
  });

  it("reads a quote typed by hand, without a file", () => {
    expect(parseQuotedQuestion("> citat\n\nfråga")).toEqual({
      quote: { text: "citat", fileName: null, locator: null },
      text: "fråga"
    });
  });

  it("leaves text that only starts with a quote mark alone", () => {
    for (const question of ["> 5 är större\nän 3", ">inget mellanslag\n\nfråga", "Vanlig fråga"]) {
      expect(parseQuotedQuestion(question)).toEqual({ quote: null, text: question });
    }
  });
});

it("retains the exact file and location through history serialization", () => {
  const quote = {
    fileId: "11111111-2222-3333-4444-555555555555",
    fileName: "Budget, 2025.xlsx",
    text: "D · Budget: 21 245",
    locator: 'sheet "Utfall 2025", row 2 (data row 1), column D'
  };
  const parsed = parseQuotedQuestion(composeQuotedQuestion(quote, "Why this amount?"));
  expect(parsed).toEqual({ quote, text: "Why this amount?" });
  expect(quotedFileMatches(parsed.quote!, { id: quote.fileId, name: "renamed.xlsx" })).toBe(true);
  expect(quotedFileMatches(parsed.quote!, { id: "another-version", name: quote.fileName })).toBe(
    false
  );
});
it("preserves exact IDs for ordinary text quotes without a table locator", () => {
  const quote = {
    fileId: "11111111-2222-3333-4444-555555555555",
    fileName: "Report.docx",
    text: "Paragraph",
    locator: null
  };
  expect(parseQuotedQuestion(composeQuotedQuestion(quote, "Explain"))).toEqual({
    quote,
    text: "Explain"
  });
});
it("keeps filename fallback only for legacy references", () => {
  expect(
    quotedFileMatches(
      { text: "Budget", fileName: "data.xlsx", locator: null },
      { id: "legacy", name: "data.xlsx" }
    )
  ).toBe(true);
});

it("preserves a selected-row filter without pasting preview values", () => {
  const quote = {
    fileId: "12345678-1234-4234-8234-123456789012",
    fileName: "budget.xlsx",
    text: "Selected rows: 3",
    locator: 'sheet "Budget", source rows [2,4,8]'
  };
  expect(parseQuotedQuestion(composeQuotedQuestion(quote, "Compare these"))).toEqual({
    quote,
    text: "Compare these"
  });
});
