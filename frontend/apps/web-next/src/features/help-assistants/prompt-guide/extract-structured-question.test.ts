import { describe, expect, test } from "vitest";
import { extractStructuredQuestion, type PromptGuideQuestion } from "./extract-structured-question";

function makeValidEnvelope(overrides: Partial<PromptGuideQuestion> = {}): string {
  const envelope = {
    header: "Audience",
    question: "Who will primarily talk to this assistant?",
    multiSelect: false,
    options: [
      { label: "End users", description: "External public." },
      { label: "Internal staff", description: "Employees in the org." }
    ],
    ...overrides
  };
  return "```eneo-question\n" + JSON.stringify(envelope, null, 2) + "\n```";
}

describe("extractStructuredQuestion", () => {
  test("returns none for empty input and prose without a block", () => {
    expect(extractStructuredQuestion("")).toEqual({ kind: "none" });
    expect(extractStructuredQuestion("Let me ask you about audience.")).toEqual({ kind: "none" });
  });

  test("treats an unclosed eneo-question block as pending", () => {
    const text = 'Two topics left.\n\n```eneo-question\n{\n  "header":';
    const result = extractStructuredQuestion(text);
    expect(result).toEqual({ kind: "pending", proseBefore: "Two topics left.\n\n" });
  });

  test("parses a valid envelope and splits surrounding prose", () => {
    const result = extractStructuredQuestion("Recap.\n\n" + makeValidEnvelope() + "\n\nPick one.");
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.proseBefore.trim()).toBe("Recap.");
      expect(result.proseAfter.trim()).toBe("Pick one.");
      expect(result.question.header).toBe("Audience");
      expect(result.question.options[0]?.label).toBe("End users");
    }
  });

  test("supports free-text intake questions", () => {
    const result = extractStructuredQuestion(makeValidEnvelope({ options: [] }));
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") expect(result.question.options).toEqual([]);
  });

  test("uses the last canonical block when several appear", () => {
    const text =
      makeValidEnvelope({ header: "First" }) + "\n\n" + makeValidEnvelope({ header: "Second" });
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") expect(result.question.header).toBe("Second");
  });

  test("accepts fallback language tags only when the body validates", () => {
    const envelope = JSON.stringify({
      header: "Audience",
      question: "Who will primarily talk to this assistant?",
      multiSelect: false,
      options: [{ label: "End users" }, { label: "Internal staff" }]
    });
    expect(extractStructuredQuestion("```question\n" + envelope + "\n```").kind).toBe("parsed");
    expect(extractStructuredQuestion("```json\n" + envelope + "\n```").kind).toBe("parsed");
    expect(extractStructuredQuestion('```json\n{"foo": "bar"}\n```')).toEqual({ kind: "none" });
  });

  test("canonical invalid blocks are not replaced by fallback blocks", () => {
    const fallback = JSON.stringify({
      header: "Fallback",
      question: "fallback-q",
      multiSelect: false,
      options: [{ label: "a" }, { label: "b" }]
    });
    const result = extractStructuredQuestion(
      "```question\n" + fallback + "\n```\n\n```eneo-question\ngarbage\n```"
    );
    expect(result.kind).toBe("invalid");
  });

  test("repairs common JSON mistakes", () => {
    const trailingComma =
      '{"header":"h","question":"q","multiSelect":false,"options":[{"label":"a"},{"label":"b"},]}';
    expect(extractStructuredQuestion("```eneo-question\n" + trailingComma + "\n```").kind).toBe(
      "parsed"
    );

    const curly =
      "{“header”:“h”,“question”:“q”,“multiSelect”:false,“options”:[{“label”:“a”},{“label”:“b”}]}";
    expect(extractStructuredQuestion("```eneo-question\n" + curly + "\n```").kind).toBe("parsed");
  });

  test("rejects malformed envelopes", () => {
    const invalidBodies = [
      "not even json",
      "null",
      '"a string"',
      JSON.stringify({ header: "h", question: "q", multiSelect: false, options: [{ label: "a" }] }),
      JSON.stringify({
        header: "h",
        question: "q",
        multiSelect: false,
        options: Array.from({ length: 7 }, (_, index) => ({ label: `o${index}` }))
      }),
      JSON.stringify({
        header: "x".repeat(101),
        question: "q",
        multiSelect: false,
        options: [{ label: "a" }, { label: "b" }]
      })
    ];

    for (const body of invalidBodies) {
      expect(extractStructuredQuestion("```eneo-question\n" + body + "\n```").kind).toBe("invalid");
    }
  });
});
