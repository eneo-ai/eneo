import { getSchema } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import { changesBetween } from "./changes";
import { documentExtensions, documentMarkdown } from "./extensions";

const schema = getSchema(documentExtensions());
const parse = (source: string) => schema.nodeFromJSON(documentMarkdown().parse(source));

/** The changes as text: what was added, as the current document reads it, and what was removed. */
function describe_(previous: string, current: string) {
  const doc = parse(current);
  return changesBetween(previous, current).map((change) =>
    change.kind === "added"
      ? { added: doc.textBetween(change.from, change.to, "\n") }
      : { removed: change.text }
  );
}

describe("what a version changed against the one before it", () => {
  it("is nothing for the same text", () => {
    expect(changesBetween("# Plan\n\nEtt stycke.\n", "# Plan\n\nEtt stycke.\n")).toEqual([]);
  });

  it("marks the words put in and names the words taken out, in place", () => {
    expect(describe_("Mötet hålls på måndag.\n", "Mötet hålls på fredag.\n")).toEqual([
      { added: "fredag" },
      { removed: "måndag" }
    ]);
  });

  it("marks a paragraph added at the end", () => {
    expect(describe_("Första.\n", "Första.\n\nAndra.\n")).toEqual([{ added: "Andra." }]);
  });

  it("names a paragraph taken out where it stood", () => {
    const changes = changesBetween("Första.\n\nAndra.\n\nTredje.\n", "Första.\n\nTredje.\n");
    expect(changes).toEqual([{ kind: "removed", at: expect.any(Number), text: "Andra." }]);
    // The removed text stands at the start of the paragraph that follows now.
    const doc = parse("Första.\n\nTredje.\n");
    expect(changes[0]).toMatchObject({ at: doc.child(0).nodeSize + 1 });
  });
});
