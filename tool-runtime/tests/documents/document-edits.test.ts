import { describe, expect, test } from "bun:test";
import { ToolError } from "../../src/errors";
import { applyEdits, type DocumentEdit } from "../../src/tools/documents/edits";

const SOURCE = `# Projektplan

Leveransen sker i tre etapper under hösten.

## Ansvar

- IT-enheten ansvarar för integrationen.
- IT-enheten ansvarar för driften.
`;

function codeOf(edits: DocumentEdit[], source = SOURCE, maxChars = 50_000): string {
  try {
    applyEdits(source, edits, maxChars);
  } catch (error) {
    if (error instanceof ToolError) return error.code;
    throw error;
  }
  return "";
}

describe("applyEdits", () => {
  test("replaces a passage and leaves the rest untouched", () => {
    const edited = applyEdits(
      SOURCE,
      [
        {
          find: "i tre etapper under hösten",
          replace: "i tre etapper. Pilotgruppen startar först",
        },
      ],
      50_000,
    );
    expect(edited).toBe(
      SOURCE.replace("i tre etapper under hösten", "i tre etapper. Pilotgruppen startar först"),
    );
  });

  test("an empty replacement removes the passage", () => {
    const edited = applyEdits(SOURCE, [{ find: " under hösten", replace: "" }], 50_000);
    expect(edited).toContain("Leveransen sker i tre etapper.");
  });

  test("occurrence picks one of several matches", () => {
    const edited = applyEdits(
      SOURCE,
      [{ find: "IT-enheten", replace: "Driftenheten", occurrence: 2 }],
      50_000,
    );
    expect(edited).toContain("- IT-enheten ansvarar för integrationen.");
    expect(edited).toContain("- Driftenheten ansvarar för driften.");
  });

  test("a later edit sees the result of an earlier one", () => {
    const edited = applyEdits(
      SOURCE,
      [
        { find: "tre etapper", replace: "fyra etapper" },
        { find: "fyra etapper under hösten", replace: "fyra etapper under våren" },
      ],
      50_000,
    );
    expect(edited).toContain("Leveransen sker i fyra etapper under våren.");
  });

  test("matches text across Windows line endings", () => {
    const edited = applyEdits(
      SOURCE.replace(/\n/g, "\r\n"),
      [{ find: "## Ansvar\n\n- IT-enheten", replace: "## Ansvar\n\n- Bygglovsenheten" }],
      50_000,
    );
    expect(edited).toContain("## Ansvar\n\n- Bygglovsenheten ansvarar för integrationen.");
  });

  test("text that is not in the document is refused", () => {
    expect(codeOf([{ find: "styrgruppen", replace: "ledningsgruppen" }])).toBe("EDIT_NOT_FOUND");
  });

  test("a repeated passage needs an occurrence, and the error gives the count", () => {
    expect(() => applyEdits(SOURCE, [{ find: "IT-enheten", replace: "X" }], 50_000)).toThrow(
      /occurs 2 times/,
    );
    expect(codeOf([{ find: "IT-enheten", replace: "X" }])).toBe("EDIT_AMBIGUOUS");
  });

  test("an occurrence past the last match is refused", () => {
    expect(codeOf([{ find: "IT-enheten", replace: "X", occurrence: 3 }])).toBe("EDIT_OCCURRENCE");
  });

  test("edits that change nothing are refused", () => {
    expect(codeOf([{ find: "Projektplan", replace: "Projektplan" }])).toBe("EDIT_NO_CHANGE");
  });

  test("a result over the content limit is refused", () => {
    expect(codeOf([{ find: "Projektplan", replace: "P".repeat(200) }], SOURCE, 100)).toBe(
      "CONTENT_TOO_LONG",
    );
  });

  test("a failing edit names its position", () => {
    expect(() =>
      applyEdits(
        SOURCE,
        [
          { find: "tre etapper", replace: "fyra etapper" },
          { find: "saknas", replace: "finns" },
        ],
        50_000,
      ),
    ).toThrow(/^Edit 2:/);
  });
});
