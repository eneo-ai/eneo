import { describe, expect, test } from "vitest";
import { extractFinalPrompt } from "./extract-final-prompt";

describe("extractFinalPrompt", () => {
  test("returns null while the guide is still interviewing", () => {
    expect(extractFinalPrompt("Great. **Who** is the audience?")).toBeNull();
  });

  test("ignores inline code", () => {
    expect(extractFinalPrompt("Set the `temperature` low.")).toBeNull();
  });

  test("returns the fenced block content", () => {
    const reply = "Here are your improved instructions:\n\n```\nYou are helpful.\n```";
    expect(extractFinalPrompt(reply)).toBe("You are helpful.");
  });

  test("accepts known final-prompt language tags", () => {
    for (const lang of ["prompt", "markdown", "md", "system", "instructions", "PROMPT"]) {
      expect(extractFinalPrompt("```" + lang + "\nYou are helpful.\n```")).toBe("You are helpful.");
    }
  });

  test("preserves internal newlines and structure", () => {
    const body = "You are a support agent.\n\nAlways:\n- Greet\n- Ask one question";
    expect(extractFinalPrompt("Final:\n\n```\n" + body + "\n```")).toBe(body);
  });

  test("returns the last accepted fenced block", () => {
    const reply = "```\nfirst draft\n```\n\n```\nfinal draft\n```";
    expect(extractFinalPrompt(reply)).toBe("final draft");
  });

  test("rejects structured questions and arbitrary code blocks", () => {
    const question =
      '```eneo-question\n{"header":"x","question":"y","multiSelect":false,"options":[{"label":"a"},{"label":"b"}]}\n```';
    expect(extractFinalPrompt(question)).toBeNull();

    for (const lang of ["json", "yaml", "python", "ts", "bash"]) {
      expect(extractFinalPrompt("```" + lang + '\n{"x":1}\n```')).toBeNull();
    }
  });

  test("keeps the last accepted prompt even if a rejected block appears later", () => {
    const reply = "Final:\n```\nYou are concise.\n```\nDebug:\n```json\n{}\n```";
    expect(extractFinalPrompt(reply)).toBe("You are concise.");
  });
});
