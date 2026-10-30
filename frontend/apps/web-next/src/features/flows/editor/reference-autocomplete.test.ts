import { describe, expect, it } from "vitest";
import { completeReference, referenceSuggestions, triggerAt } from "./reference-autocomplete";
import type { VariableGroup } from "./step-variables";

const typed = { typed: true, wasAt: false };
const moved = { typed: false, wasAt: false };

describe("the reference triggers", () => {
  it("opens on an unclosed {{ before the caret, with what was typed after it", () => {
    expect(triggerAt("Läs {{ step", 11, moved)).toEqual({
      kind: "braces",
      start: 4,
      query: "step"
    });
    expect(triggerAt("Läs {{step_1}} nu", 17, moved)).toBeNull();
  });

  it("opens on an @ typed at the start of a word, until a space follows", () => {
    expect(triggerAt("Läs @sam", 8, typed)).toEqual({ kind: "at", start: 4, query: "sam" });
    expect(triggerAt("(@", 2, typed)).toEqual({ kind: "at", start: 1, query: "" });
    expect(triggerAt("Läs @sam nu", 11, typed)).toBeNull();
    expect(triggerAt("anna@kommun.se", 11, typed)).toBeNull();
  });

  it("does not open on an @ the caret only passes, but follows one that is open", () => {
    expect(triggerAt("Läs @sam", 8, moved)).toBeNull();
    expect(triggerAt("Läs @sa", 7, { typed: false, wasAt: true })).toEqual({
      kind: "at",
      start: 4,
      query: "sa"
    });
  });
});

describe("the reference suggestions", () => {
  const groups: VariableGroup[] = [
    { type: "run", entries: [{ token: "datum", kind: { type: "date" } }] },
    {
      type: "step",
      stepOrder: 1,
      stepName: "Sammanfatta",
      entries: [{ token: "step_1.output.text", kind: { type: "step_text" } }]
    }
  ];
  const label = (entry: { token: string }, group: VariableGroup) =>
    group.type === "step" ? `Steg ${group.stepOrder}: ${group.stepName}` : entry.token;

  it("lists every reference the step can read, filtered by name or reference", () => {
    expect(referenceSuggestions(groups, "", label).map((item) => item.token)).toEqual([
      "datum",
      "step_1.output.text"
    ]);
    expect(referenceSuggestions(groups, "samman", label)).toEqual([
      { token: "step_1.output.text", label: "Steg 1: Sammanfatta" }
    ]);
    expect(referenceSuggestions(groups, "OUTPUT", label)).toHaveLength(1);
    expect(referenceSuggestions(groups, "inget", label)).toEqual([]);
  });
});

describe("completing a reference", () => {
  it("replaces the trigger and what was typed after it, and puts the caret after it", () => {
    const text = "Läs @sam och";
    const trigger = triggerAt(text, 8, typed)!;
    expect(completeReference(text, trigger, 8, "step_1.output.text")).toEqual({
      text: "Läs {{step_1.output.text}} och",
      caret: 26
    });
  });

  it("replaces a whole reference the caret is inside", () => {
    const text = "Läs {{step_1.out}} och {{datum}}";
    const trigger = triggerAt(text, 12, moved)!;
    expect(completeReference(text, trigger, 12, "step_2.output.text").text).toBe(
      "Läs {{step_2.output.text}} och {{datum}}"
    );
    const open = "Läs {{ste och {{datum}}";
    expect(completeReference(open, triggerAt(open, 9, moved)!, 9, "datum").text).toBe(
      "Läs {{datum}} och {{datum}}"
    );
  });
});
