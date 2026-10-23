import { getSchema } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import { changesBetween, documentChanges } from "./changes";
import { documentExtensions, documentMarkdown } from "./extensions";

const schema = getSchema(documentExtensions());
const parse = (source: string) => schema.nodeFromJSON(documentMarkdown().parse(source));

/** The changes as the reader sees them: added text, and removed text marked with a minus. */
function shown(previous: string, current: string) {
  const doc = parse(current);
  return changesBetween(previous, current).map((change) =>
    change.kind === "added" ? doc.textBetween(change.from, change.to, " ") : `-${change.text}`
  );
}

describe("the changes between two versions", () => {
  it("mark added words where they stand in the new version", () => {
    expect(
      shown("# Plan\n\nFas ett startar i maj.\n", "# Plan\n\nFas ett startar i juni.\n")
    ).toEqual(["juni", "-maj"]);
  });

  it("place a removed paragraph where it was", () => {
    const current = parse("Ett stycke.\n\nSlut.\n");
    const changes = documentChanges(
      parse("Ett stycke.\n\nEtt annat stycke som försvinner.\n\nSlut.\n"),
      current
    );

    expect(changes).toHaveLength(1);
    const [change] = changes;
    if (change.kind !== "removed") throw new Error("expected a removal");
    expect(change.text).toBe("Ett annat stycke som försvinner.");
    // It stood between the two kept paragraphs.
    expect(current.textBetween(change.at, current.content.size, " ")).toBe("Slut.");
  });

  it("are none for identical versions", () => {
    expect(changesBetween("# Plan\n\n- a\n- b\n", "# Plan\n\n- a\n- b\n")).toEqual([]);
  });

  it("follow a change into a table cell", () => {
    expect(
      shown(
        "| Fas | Start |\n| --- | --- |\n| Design | Månad 2 |\n",
        "| Fas | Start |\n| --- | --- |\n| Design | Månad 3 |\n"
      )
      // Down to the word that differs.
    ).toEqual(["3", "-2"]);
  });
});
