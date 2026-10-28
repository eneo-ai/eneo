import { describe, expect, test } from "bun:test";
import { ToolError } from "../../src/errors";
import { applyEdits, nearestPassage, type DocumentEdit } from "../../src/tools/documents/edits";

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

  describe("the stored document differs from what the model wrote", () => {
    const HANDLE = "eneo-file:10d0cab3e3ed4508b37e4ea6fbc22201";
    const REPORT = `# Analys av risker

## Riskområden

![Antal identifierade risker per riskområde](${HANDLE} "Figur 1")

## Riskvärden

| Risk-ID | Riskrubrik             | Riskvärde |
|---------|------------------------|-----------|
| 1       | Brister i säkerhet     | **12**    |
| 5       | Avsaknad av rutiner    | **12**    |
`;

    test("an image placed as image:ID is found as its stored eneo-file line", () => {
      const edited = applyEdits(
        REPORT,
        [
          {
            find: "![Antal identifierade risker per riskområde](image:riskomraden)",
            replace:
              "![Antal identifierade risker per riskområde](image:riskomraden)\n\n### Risker med högst riskvärde\n\n| Risk-ID | Riskvärde |\n|---|---|\n| 1 | **12** |",
          },
        ],
        50_000,
      );
      expect(edited).toContain(
        `![Antal identifierade risker per riskområde](${HANDLE} "Figur 1")\n\n### Risker med högst riskvärde\n\n| Risk-ID | Riskvärde |`,
      );
      expect(edited).not.toContain("image:riskomraden");
    });

    test("the replacement's image marker takes the replaced image's line by alt text, else the only one", () => {
      const edited = applyEdits(
        REPORT,
        [
          {
            find: "![Antal identifierade risker per riskområde](image:riskomraden)",
            replace: "Figuren nedan visar fördelningen.\n\n![Risker per område](image:figur)",
          },
        ],
        50_000,
      );
      expect(edited).toContain(
        `Figuren nedan visar fördelningen.\n\n![Risker per område](${HANDLE} "Figur 1")`,
      );
    });

    test("an image the replaced text does not hold cannot be placed by marker", () => {
      expect(
        codeOf(
          [{ find: "## Riskvärden", replace: "## Riskvärden\n\n![Ny graf](image:ny)" }],
          REPORT,
        ),
      ).toBe("EDIT_IMAGE_UNKNOWN");
    });

    test("a stored image line in the replacement stays as written", () => {
      const edited = applyEdits(
        REPORT,
        [
          {
            find: `![Antal identifierade risker per riskområde](${HANDLE} "Figur 1")`,
            replace: `![Antal risker per område](${HANDLE} "Figur 1")`,
          },
        ],
        50_000,
      );
      expect(edited).toContain(`![Antal risker per område](${HANDLE} "Figur 1")`);
    });

    test("a table row is found whatever its cell padding", () => {
      const edited = applyEdits(
        REPORT,
        [
          {
            find: "| 5 | Avsaknad av rutiner | **12** |",
            replace: "| 5 | Avsaknad av rutiner | **16** |",
          },
        ],
        50_000,
      );
      expect(edited).toContain("| 5 | Avsaknad av rutiner | **16** |\n");
      expect(edited).toContain("| 1       | Brister i säkerhet     | **12**    |\n");
    });

    test("a padded find matches a compact table, separator row included", () => {
      const compact = "| A | B |\n|---|:--:|\n| 1 | 2 |\n";
      const edited = applyEdits(
        compact,
        [
          {
            find: "| A   | B   |\n|-----|:---:|\n| 1   | 2   |",
            replace: "| A | B |\n|---|:--:|\n| 1 | 3 |",
          },
        ],
        50_000,
      );
      expect(edited).toBe("| A | B |\n|---|:--:|\n| 1 | 3 |\n");
    });

    test("a cell's inner spacing still counts", () => {
      expect(codeOf([{ find: "| Brister  i säkerhet |", replace: "x" }], REPORT)).toBe(
        "EDIT_NOT_FOUND",
      );
    });

    test("trailing whitespace on a line does not stand in the way", () => {
      const edited = applyEdits(
        "Första raden.  \nAndra raden.\n",
        [{ find: "Första raden.\nAndra raden.", replace: "En rad." }],
        50_000,
      );
      expect(edited).toBe("En rad.\n");
    });

    test("the not-found error shows the nearest passage of the document", () => {
      expect(() =>
        applyEdits(
          REPORT,
          [
            {
              find: "![Antal identifierade risker per riskområde](image:annan)\n\n## Slutsats",
              replace: "x",
            },
          ],
          50_000,
        ),
      ).toThrow(
        `The nearest passage in the document reads:\n![Antal identifierade risker per riskområde](${HANDLE} "Figur 1")`,
      );
      expect(() =>
        applyEdits(REPORT, [{ find: "brister i Säkerhet och rutiner", replace: "x" }], 50_000),
      ).toThrow("| 1       | Brister i säkerhet     | **12**    |");
    });

    test("nothing resembling the text asks for the document to be read", () => {
      expect(() => applyEdits(REPORT, [{ find: "styrgruppen", replace: "x" }], 50_000)).toThrow(
        /Read the document to see its current text\.$/,
      );
      expect(nearestPassage(REPORT, "styrgruppen")).toBeUndefined();
    });
  });
});
