import { describe, expect, test } from "vitest";
import { extractStructuredQuestion, type PromptGuideQuestion } from "./extractStructuredQuestion";

// The Prompt Guide modal renders structured questions as a Claude-Code-style
// multi-choice card. The model is instructed to emit each question as a
// fenced ` ```eneo-question ` block with a JSON envelope; the parser below
// is what turns that convention into something the UI can render — and what
// hides half-streamed blocks before they're applyable. The cases here are
// the contract; if any breaks, the modal will either flicker garbled JSON
// at the user (pending case) or render an unanswerable card (validation
// cases), so add a regression test before relaxing any rule here.

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

describe("extractStructuredQuestion — empty / no block", () => {
  test("returns 'none' for empty input", () => {
    expect(extractStructuredQuestion("")).toEqual({ kind: "none" });
    expect(extractStructuredQuestion("   \n  ")).toEqual({ kind: "none" });
  });

  test("returns 'none' for prose without an eneo-question block", () => {
    expect(extractStructuredQuestion("Let me ask you about audience.")).toEqual({
      kind: "none"
    });
  });

  test("ignores an unrelated fenced block", () => {
    expect(extractStructuredQuestion('```json\n{"x":1}\n```')).toEqual({ kind: "none" });
  });
});

describe("extractStructuredQuestion — pending (stream still open)", () => {
  test("treats a bare opener with no closing fence as pending", () => {
    const result = extractStructuredQuestion("```eneo-question");
    expect(result).toEqual({ kind: "pending", proseBefore: "" });
  });

  test("treats prose + opener + partial JSON as pending", () => {
    const text = 'Two more topics to cover.\n\n```eneo-question\n{\n  "header":';
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("pending");
    if (result.kind === "pending") {
      expect(result.proseBefore).toBe("Two more topics to cover.\n\n");
    }
  });

  test("after a complete block, a second unclosed opener resolves to pending", () => {
    const text = makeValidEnvelope() + '\n\nNext up:\n\n```eneo-question\n{"header":"Tone"';
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("pending");
    if (result.kind === "pending") {
      // Pending offset points at the second opener — never inside the first.
      expect(result.proseBefore.endsWith("Next up:\n\n")).toBe(true);
    }
  });
});

describe("extractStructuredQuestion — parsed (valid envelope)", () => {
  test("parses a minimal valid block", () => {
    const result = extractStructuredQuestion(makeValidEnvelope());
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.question.header).toBe("Audience");
      expect(result.question.question).toBe("Who will primarily talk to this assistant?");
      expect(result.question.multiSelect).toBe(false);
      expect(result.question.options).toHaveLength(2);
      expect(result.question.options[0].label).toBe("End users");
      expect(result.question.options[0].description).toBe("External public.");
    }
  });

  test("splits surrounding prose into before/after", () => {
    const text = "Your prompt is concise.\n\n" + makeValidEnvelope() + "\n\nPick one.";
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.proseBefore.trim()).toBe("Your prompt is concise.");
      expect(result.proseAfter.trim()).toBe("Pick one.");
    }
  });

  test("collapses empty description to undefined", () => {
    const envelope = makeValidEnvelope({
      options: [{ label: "Yes", description: "" }, { label: "No" }]
    });
    const result = extractStructuredQuestion(envelope);
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.question.options[0].description).toBeUndefined();
      expect(result.question.options[1].description).toBeUndefined();
    }
  });

  test("accepts multiSelect=true", () => {
    const result = extractStructuredQuestion(makeValidEnvelope({ multiSelect: true }));
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.question.multiSelect).toBe(true);
    }
  });

  test("parses a free-text intake question (options: [])", () => {
    const envelope = makeValidEnvelope({ options: [] });
    const result = extractStructuredQuestion(envelope);
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.question.options).toEqual([]);
      expect(result.question.header).toBe("Audience");
    }
  });

  test("when two complete blocks appear in one turn, only the LAST is returned", () => {
    // The system prompt forbids this but models occasionally over-share.
    // The user is being asked the latest question; earlier ones are stale.
    const first = makeValidEnvelope({ header: "First" });
    const second = makeValidEnvelope({ header: "Second" });
    const text = first + "\n\nLet's also consider:\n\n" + second;
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("parsed");
    if (result.kind === "parsed") {
      expect(result.question.header).toBe("Second");
      // proseBefore swallows everything up to (but not including) the
      // second block — including the first block's text.
      expect(result.proseBefore).toContain("First");
    }
  });
});

describe("extractStructuredQuestion — fallback language tags", () => {
  test("accepts a ` ```question` block whose body is a valid envelope", () => {
    const envelope = JSON.stringify({
      header: "Audience",
      question: "Who will primarily talk to this assistant?",
      multiSelect: false,
      options: [{ label: "End users" }, { label: "Internal staff" }]
    });
    const text = "```question\n" + envelope + "\n```";
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("parsed");
  });

  test("accepts a ` ```json` block whose body is a valid envelope", () => {
    const envelope = JSON.stringify({
      header: "Audience",
      question: "Who will primarily talk to this assistant?",
      multiSelect: false,
      options: [{ label: "End users" }, { label: "Internal staff" }]
    });
    const text = "```json\n" + envelope + "\n```";
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("parsed");
  });

  test("does NOT hijack an unrelated ` ```json` snippet that lacks the envelope shape", () => {
    // A real JSON snippet the LLM is showing for some other reason — eg.
    // a logging payload — must not get rendered as a card.
    const text = '```json\n{"foo": "bar"}\n```';
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("none");
  });

  test("canonical eneo-question wins over a co-existing ```question fallback", () => {
    // Even when the canonical block is malformed, render it as invalid
    // rather than silently substituting the fallback — the user can see
    // the LLM mistake instead of getting confusingly different content.
    const fallback = JSON.stringify({
      header: "Fallback",
      question: "fallback-q",
      multiSelect: false,
      options: [{ label: "a" }, { label: "b" }]
    });
    const text = "```question\n" + fallback + "\n```\n\n```eneo-question\ngarbage\n```";
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("invalid");
  });
});

describe("extractStructuredQuestion — JSON repair", () => {
  function repairCase(rawBody: string): { kind: string } {
    return extractStructuredQuestion("```eneo-question\n" + rawBody + "\n```");
  }

  test("accepts an envelope with trailing commas after options", () => {
    const body =
      '{"header":"h","question":"q","multiSelect":false,"options":[{"label":"a"},{"label":"b"},]}';
    expect(repairCase(body).kind).toBe("parsed");
  });

  test("accepts an envelope using curly double quotes", () => {
    // Smart-quoted keys + values — common from voice-tuned models.
    const body =
      "{“header”:“h”,“question”:“q”,“multiSelect”:false,“options”:[{“label”:“a”},{“label”:“b”}]}";
    expect(repairCase(body).kind).toBe("parsed");
  });

  test("still rejects bodies that cannot be repaired", () => {
    expect(repairCase("totally not json").kind).toBe("invalid");
    expect(repairCase('{ "header": "h"').kind).toBe("invalid");
  });
});

describe("extractStructuredQuestion — invalid (malformed envelope)", () => {
  function expectInvalid(body: string): void {
    const result = extractStructuredQuestion("```eneo-question\n" + body + "\n```");
    expect(result.kind).toBe("invalid");
  }

  test("rejects non-JSON body", () => {
    expectInvalid("not even json");
    expectInvalid("{ unclosed");
  });

  test("rejects JSON that is not an object", () => {
    expectInvalid("null");
    expectInvalid('"a string"');
    expectInvalid("[1,2,3]");
    expectInvalid("42");
  });

  test("rejects missing or empty required fields", () => {
    expectInvalid(JSON.stringify({ question: "q", multiSelect: false, options: [] }));
    expectInvalid(JSON.stringify({ header: "", question: "q", multiSelect: false, options: [] }));
    expectInvalid(JSON.stringify({ header: "h", multiSelect: false, options: [] }));
    expectInvalid(JSON.stringify({ header: "h", question: "q", options: [] }));
  });

  test("rejects multiSelect that is not a boolean", () => {
    expectInvalid(
      JSON.stringify({
        header: "h",
        question: "q",
        multiSelect: "false",
        options: [{ label: "a" }, { label: "b" }]
      })
    );
  });

  test("rejects exactly 1 option (free-text intake uses 0, multi-choice uses 2+)", () => {
    const base = { header: "h", question: "q", multiSelect: false };
    expectInvalid(JSON.stringify({ ...base, options: [{ label: "only one" }] }));
  });

  test("rejects more than 6 options", () => {
    const base = { header: "h", question: "q", multiSelect: false };
    expectInvalid(
      JSON.stringify({
        ...base,
        options: Array.from({ length: 7 }, (_, i) => ({ label: `o${i}` }))
      })
    );
  });

  test("rejects option label longer than 200 characters", () => {
    const longLabel = "x".repeat(201);
    expectInvalid(
      JSON.stringify({
        header: "h",
        question: "q",
        multiSelect: false,
        options: [{ label: longLabel }, { label: "ok" }]
      })
    );
  });

  test("rejects header longer than 100 characters", () => {
    expectInvalid(
      JSON.stringify({
        header: "x".repeat(101),
        question: "q",
        multiSelect: false,
        options: [{ label: "a" }, { label: "b" }]
      })
    );
  });

  test("rejects question longer than 1000 characters", () => {
    expectInvalid(
      JSON.stringify({
        header: "h",
        question: "x".repeat(1001),
        multiSelect: false,
        options: [{ label: "a" }, { label: "b" }]
      })
    );
  });

  test("rejects description longer than 500 characters", () => {
    expectInvalid(
      JSON.stringify({
        header: "h",
        question: "q",
        multiSelect: false,
        options: [{ label: "a", description: "x".repeat(501) }, { label: "b" }]
      })
    );
  });

  test("rejects an option that is not an object", () => {
    expectInvalid(
      JSON.stringify({
        header: "h",
        question: "q",
        multiSelect: false,
        options: ["just a string", { label: "ok" }]
      })
    );
  });

  test("splits prose around an invalid block so the rest of the turn still renders", () => {
    const text = "Quick recap:\n\n```eneo-question\nnot json\n```\n\nMy apologies.";
    const result = extractStructuredQuestion(text);
    expect(result.kind).toBe("invalid");
    if (result.kind === "invalid") {
      expect(result.proseBefore.trim()).toBe("Quick recap:");
      expect(result.proseAfter.trim()).toBe("My apologies.");
    }
  });
});
