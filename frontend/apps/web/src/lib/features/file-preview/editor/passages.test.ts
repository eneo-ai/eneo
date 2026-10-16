import { getSchema } from "@tiptap/core";
import { CellSelection, TableMap } from "@tiptap/pm/tables";
import { describe, expect, it } from "vitest";
import { isLocator } from "../passageLocator";
import { documentExtensions, documentMarkdown } from "./extensions";
import { cellSelectionQuote, findPassageSpans, locateSelection } from "./passages";

const schema = getSchema(documentExtensions());
const parse = (source: string) => schema.nodeFromJSON(documentMarkdown().parse(source));

const TABLE =
  "# Tidplan\n\n| Fas | Innehåll | Start |\n| --- | --- | --- |\n| Förberedelse | Kartlägga | Månad 1 |\n| Design | Utforma | Månad 2 |\n| Migrering | Rensa | Månad 3 |\n\nSlut.\n";

/** The cells of the document's first table, by row and column from 0. */
function cells(doc: ReturnType<typeof parse>) {
  let start = 0;
  doc.descendants((node, pos) => {
    if (node.type.name === "table" && !start) start = pos + 1;
    return !start;
  });
  const table = doc.nodeAt(start - 1)!;
  const map = TableMap.get(table);
  return (row: number, column: number) => start + map.map[row * map.width + column];
}

describe("a rectangle of table cells", () => {
  it("is quoted row by row and located by table, rows and columns", () => {
    const doc = parse(TABLE);
    const at = cells(doc);
    const selection = CellSelection.create(doc, at(1, 0), at(2, 1));

    const quoted = cellSelectionQuote(doc, selection);

    expect(quoted.text).toBe(
      "| Fas | Innehåll |\n| --- | --- |\n| Förberedelse | Kartlägga |\n| Design | Utforma |"
    );
    expect(quoted.locator).toBe("table 1, rows 2-3, columns 1-2");
    expect(isLocator(quoted.locator)).toBe(true);
  });

  it("is found again from its locator, cell by cell", () => {
    const doc = parse(TABLE);
    const at = cells(doc);
    const selection = CellSelection.create(doc, at(1, 0), at(2, 1));
    const quoted = cellSelectionQuote(doc, selection);

    const spans = findPassageSpans(doc, quoted.text, quoted.locator);

    expect(spans.map((span) => doc.textBetween(span.from, span.to))).toEqual([
      "Förberedelse",
      "Kartlägga",
      "Design",
      "Utforma"
    ]);
  });

  it("names a single cell in the singular", () => {
    const doc = parse(TABLE);
    const at = cells(doc);
    const quoted = cellSelectionQuote(doc, CellSelection.create(doc, at(3, 2), at(3, 2)));
    expect(quoted).toEqual({
      text: "| Start |\n| --- |\n| Månad 3 |",
      locator: "table 1, row 4, column 3"
    });
  });

  it("points at nothing when the table or cells are gone", () => {
    const doc = parse("Bara text.\n");
    expect(findPassageSpans(doc, "| x |", "table 1, row 1, column 1")).toEqual([]);
  });
});

describe("a text selection", () => {
  it("is located by occurrence only when its text repeats", () => {
    const doc = parse("Samma rad.\n\nSamma rad.\n\nAnnan rad.\n");
    const second = doc.textBetween(0, doc.content.size, "\n").indexOf("Samma", 5);
    void second;
    // The second paragraph starts after the first paragraph node (its size plus one).
    const first = doc.child(0);
    const from = first.nodeSize + 1;
    expect(locateSelection(doc, from, from + first.content.size)).toBe("occurrence 2 of 2");
    expect(locateSelection(doc, 1, 1 + first.content.size)).toBe("occurrence 1 of 2");
    const third = first.nodeSize * 2 + 1;
    expect(locateSelection(doc, third, third + 5)).toBeNull();
  });
});
