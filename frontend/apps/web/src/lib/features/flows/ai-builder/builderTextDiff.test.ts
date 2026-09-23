import { describe, expect, it } from "vitest";

import { markedView, wordDiff, type DiffPart } from "./builderTextDiff";

const show = (parts: DiffPart[] | null) =>
  parts
    ?.map((part) =>
      part.kind === "same" || part.plain
        ? part.text
        : part.kind === "removed"
          ? `[-${part.text}-]`
          : `{+${part.text}+}`
    )
    .join("");

describe("wordDiff", () => {
  it("marks only the words that change", () => {
    expect(show(wordDiff("Sammanfatta texten kort.", "Sammanfatta texten i tre meningar."))).toBe(
      "Sammanfatta texten [-kort-]{+i tre meningar+}."
    );
    expect(show(wordDiff("Samma text.", "Samma text."))).toBe("Samma text.");
  });

  it("reads a change as one struck phrase and one marked phrase", () => {
    // The spaces between the changed words would otherwise alternate
    // struck, kept, marked word by word.
    expect(show(wordDiff("Skriv en kort rapport.", "Skapa ett utkast rapport."))).toBe(
      "[-Skriv en kort-]{+Skapa ett utkast+} rapport."
    );
  });

  it("leaves the line breaks around a change unmarked, on their side", () => {
    const parts = wordDiff("Punkt ett.\n\nSlut.", "Punkt ett. Slut.")!;
    expect(parts.filter((part) => !part.plain && part.kind !== "same")).toEqual([]);
    const side = (kind: "removed" | "added") =>
      parts.filter((part) => part.kind === "same" || part.kind === kind).map((part) => part.text);
    expect(side("removed").join("")).toBe("Punkt ett.\n\nSlut.");
    expect(side("added").join("")).toBe("Punkt ett. Slut.");
  });

  it("reads the marked view as the new text, removed words struck in place", () => {
    const view = markedView(wordDiff("Skriv en kort rapport.", "Skapa ett utkast rapport.")!);
    const kept = view.filter((part) => part.kind !== "removed");
    expect(kept.map((part) => part.text).join("")).toBe("Skapa ett utkast rapport.");
    expect(view.filter((part) => part.kind === "removed").map((part) => part.text)).toEqual([
      "Skriv en kort"
    ]);
  });

  it("marks a change of spacing alone instead of hiding it", () => {
    const after = "Return exactly:\n- decision - reason";
    const view = markedView(wordDiff("Return exactly:\n- decision\n- reason", after)!);
    expect(view.filter((part) => part.marker)).toEqual([
      { kind: "removed", text: "¶", marker: "break" }
    ]);
    // Apart from the marker, the view reads exactly as the new text.
    expect(
      view
        .filter((part) => part.kind !== "removed")
        .map((part) => part.text)
        .join("")
    ).toBe(after);
  });

  it("keeps a step reference whole", () => {
    expect(
      show(
        wordDiff(
          "Läs {{ step_a.output.text }} noga.",
          "Läs {{ step_b.output.structured.beslut }} noga."
        )
      )
    ).toBe("Läs [-{{ step_a.output.text }}-]{+{{ step_b.output.structured.beslut }}+} noga.");
  });

  it("declines texts too long to compare, so the plain before and after show", () => {
    const words = (prefix: string) =>
      Array.from({ length: 1100 }, (_, index) => `${prefix}${index}`).join(" ");
    expect(wordDiff(words("a"), words("b"))).toBeNull();
  });
});
