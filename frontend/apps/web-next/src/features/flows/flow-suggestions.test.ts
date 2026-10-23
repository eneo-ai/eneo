import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { makeStep } from "./flow-fixtures";
import {
  flowSuggestionsQueryOptions,
  suggestionText,
  type FlowSuggestion
} from "./flow-suggestions";

/** The app's real catalogs, looked up by any key as the section does. */
const translator = (locale: string, messages: Record<string, string>) =>
  createTranslator({ locale, messages });
const t = translator("sv", sv);
const tEn = translator("en", en);

type Read = { channel: string; site: string; selector: string[] };

function duplicateRead(reads: Read[], contained = false): FlowSuggestion {
  return {
    code: "duplicate_read",
    fingerprint: "f".repeat(64),
    steps: ["step-2", "step-1"],
    params: { producer_step_order: 1, producer_step_id: "step-1", contained, reads },
    message: "Step 2 reads step 1 twice.",
    impact: { basis: "definition", level: contained ? "low" : "high" },
    fix: { kind: "patch" }
  };
}

const INPUT: Read = { channel: "input", site: "input_source", selector: [] };
const PROMPT: Read = {
  channel: "prompt",
  site: "assistant_prompt:step_1.output.text",
  selector: []
};

describe("suggestionText", () => {
  it("names the step read twice, as the step's input and in the prompt", () => {
    const text = suggestionText(duplicateRead([INPUT, PROMPT]), t, makeStep(2));

    expect(text.title).toBe("Svaret från steg 1 skickas två gånger");
    expect(text.explanation).toBe(
      "Steget får samma text som indata (föregående steg) och i prompten ({{ step_1.output.text }}). " +
        "Modellen läser den två gånger varje körning, vilket kostar tokens och tar plats i modellens fönster."
    );
  });

  it("says when the input is every earlier step", () => {
    const step = makeStep(3, { input_source: "all_previous_steps" });
    const text = suggestionText(duplicateRead([INPUT, PROMPT]), t, step);

    expect(text.explanation).toContain("som indata (alla tidigare steg) och i prompten");
  });

  it("names a question and a source reference where they read", () => {
    const text = suggestionText(
      duplicateRead([
        { channel: "input", site: "input_bindings.question", selector: [] },
        { channel: "input", site: "input_bindings.source_refs[1]", selector: [] },
        PROMPT
      ]),
      t
    );

    expect(text.explanation).toContain(
      "i frågan, i källhänvisning 2 och i prompten ({{ step_1.output.text }})"
    );
  });

  it("explains a field read next to the whole as contained", () => {
    const text = suggestionText(
      duplicateRead(
        [
          INPUT,
          {
            channel: "prompt",
            site: "assistant_prompt:step_1.output.structured.title",
            selector: ["structured", "title"]
          }
        ],
        true
      ),
      t,
      makeStep(2)
    );

    expect(text.title).toBe("Svaret från steg 1 skickas både helt och som ett fält");
    expect(text.explanation).toContain(
      "som indata (föregående steg) och i prompten ({{ step_1.output.structured.title }})"
    );
    expect(text.explanation).toContain("Fältet ingår redan i texten");
  });

  it("renders in English too", () => {
    const text = suggestionText(duplicateRead([INPUT, PROMPT]), tEn, makeStep(2));

    expect(text.title).toBe("The answer of step 1 is sent twice");
    expect(text.explanation).toContain("as its input (previous step) and in its prompt");
  });

  it("never shows the API message, even for a code this version does not know", () => {
    const unknown = {
      ...duplicateRead([INPUT, PROMPT]),
      code: "later_rule",
      message: "Internal English sentence."
    } as unknown as FlowSuggestion;

    const text = suggestionText(unknown, t);

    expect(text.title).toBe("Förslag");
    expect(text.explanation).not.toContain("Internal English sentence.");
  });
});

describe("flowSuggestionsQueryOptions", () => {
  it("keys the query by the draft revision, so a save refetches", () => {
    expect(flowSuggestionsQueryOptions("flow-1", 4).queryKey).toEqual([
      "flows",
      "flow-1",
      "suggestions",
      4
    ]);
    expect(flowSuggestionsQueryOptions("flow-1", 5).queryKey).not.toEqual(
      flowSuggestionsQueryOptions("flow-1", 4).queryKey
    );
  });
});
