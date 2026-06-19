import { describe, expect, test } from "vitest";
import { extractFinalPrompt } from "./extractFinalPrompt";

// The Prompt Guide modal surfaces an "Apply" affordance only once the guide has
// produced its final prompt, which the backend prompt instructs it to emit as
// the only fenced code block in the reply. extractFinalPrompt is what turns that
// convention into the exact text Apply writes into the editor — so the guide's
// questions never become applyable, and the right block wins when several exist.
describe("extractFinalPrompt", () => {
  test("returns null while the guide is still interviewing (no fenced block)", () => {
    expect(
      extractFinalPrompt("Great. **Who** is the audience, and what tone should it use?")
    ).toBeNull();
  });

  test("ignores inline code (codespan) — only fenced blocks count", () => {
    expect(extractFinalPrompt("Set the `temperature` low for consistency.")).toBeNull();
  });

  test("returns the fenced block content, without the fences", () => {
    const reply = "Here are your improved instructions:\n\n```\nYou are a helpful assistant.\n```";
    expect(extractFinalPrompt(reply)).toBe("You are a helpful assistant.");
  });

  test("strips a language tag and keeps the body", () => {
    const reply = "```text\nYou answer only in Swedish.\n```";
    expect(extractFinalPrompt(reply)).toBe("You answer only in Swedish.");
  });

  test("preserves internal newlines and structure", () => {
    const body = "You are a support agent.\n\nAlways:\n- Greet the user\n- Ask one question";
    expect(extractFinalPrompt("Final:\n\n```\n" + body + "\n```")).toBe(body);
  });

  test("returns the last fenced block when several are present", () => {
    const reply =
      "```\nfirst draft\n```\n\nOn reflection, this is better:\n\n```\nfinal draft\n```";
    expect(extractFinalPrompt(reply)).toBe("final draft");
  });

  test("finds the block even after a list of suggestions", () => {
    const reply =
      "I'd change:\n1. Be specific\n2. Add a tone\n\n```\nYou are concise and friendly.\n```";
    expect(extractFinalPrompt(reply)).toBe("You are concise and friendly.");
  });

  test("returns null for empty or whitespace input", () => {
    expect(extractFinalPrompt("")).toBeNull();
    expect(extractFinalPrompt("   \n  ")).toBeNull();
  });

  test("accepts the language tags the guide may emit for the final artifact", () => {
    for (const lang of ["prompt", "markdown", "md", "system", "instructions"]) {
      const reply = "```" + lang + "\nYou are a helpful assistant.\n```";
      expect(extractFinalPrompt(reply)).toBe("You are a helpful assistant.");
    }
  });

  test("language tag matching is case-insensitive", () => {
    expect(extractFinalPrompt("```PROMPT\nYou are a helpful assistant.\n```")).toBe(
      "You are a helpful assistant."
    );
  });

  test("rejects an eneo-question block as the final prompt", () => {
    // The interview-time question envelope must never be applied as the
    // assistant's instructions — that's what `extractStructuredQuestion`
    // is for.
    const reply =
      '```eneo-question\n{"header":"x","question":"y","multiSelect":false,"options":[{"label":"a"},{"label":"b"}]}\n```';
    expect(extractFinalPrompt(reply)).toBeNull();
  });

  test("rejects arbitrary code-fence languages so they can't be misapplied", () => {
    for (const lang of ["json", "yaml", "python", "ts", "bash"]) {
      const reply = "```" + lang + '\n{"x":1}\n```';
      expect(extractFinalPrompt(reply)).toBeNull();
    }
  });

  test("picks the last accepted block even if a rejected block appears later", () => {
    // If the model emits the final prompt and then accidentally wraps a
    // post-script in a json fence, the artifact still wins.
    const reply = "Final:\n```\nYou are concise.\n```\nDebug payload:\n```json\n{}\n```";
    expect(extractFinalPrompt(reply)).toBe("You are concise.");
  });
});
