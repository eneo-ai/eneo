import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { makeStep } from "./flow-fixtures";
import {
  flowSuggestions,
  flowSuggestionsQueryOptions,
  shownSuggestions,
  suggestionRequest,
  suggestionsByStep,
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
      "Steget får samma text som indata (föregående steg) och i prompten ({{step_1.output.text}}). " +
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
      "i frågan, i källhänvisning 2 och i prompten ({{step_1.output.text}})"
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
      "som indata (föregående steg) och i prompten ({{step_1.output.structured.title}})"
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

const STEPS = [
  makeStep(1, { user_description: "Sammanfatta" }),
  makeStep(2, { user_description: "Skriv svar" }),
  makeStep(3, { user_description: "Granska" })
];

function suggestion(
  code: string,
  steps: string[],
  params: Record<string, unknown>
): FlowSuggestion {
  return {
    code,
    fingerprint: `${code}-${steps.join("-")}`,
    steps,
    params,
    message: "English.",
    impact: { basis: "definition", level: "low" },
    fix: { kind: "advice" }
  } as unknown as FlowSuggestion;
}

describe("suggestionText with the draft's steps", () => {
  it("writes the steps and values it names as the chat does, so they show as pills", () => {
    const text = suggestionText(duplicateRead([INPUT, PROMPT]), t, STEPS[1], STEPS);
    expect(text.title).toBe("Svaret från @[Sammanfatta](step:step-1) skickas två gånger");
    expect(text.explanation).toContain("i prompten ({{step_1.output.text}})");
  });

  it.each([
    [
      suggestion("broad_all_previous_steps", ["step-3"], {
        earlier_step_count: 2,
        derived: [{ step_order: 2, from_step_order: 1 }]
      }),
      "Steget får alla 2 tidigare steg som underlag",
      "Steget får både @[Sammanfatta](step:step-1) och @[Skriv svar](step:step-2), som bygger på det"
    ],
    [
      suggestion("whole_structured_read", ["step-3", "step-1"], {
        producer_step_order: 1,
        producer_step_id: "step-1",
        fields: ["a", "b", "c", "d"]
      }),
      "Steget läser alla 4 fält från @[Sammanfatta](step:step-1)",
      "med fälten a, b, c och d"
    ],
    [
      suggestion("unread_contract_fields", ["step-2"], { fields: ["titel", "datum"] }),
      "Inget senare steg läser fälten {{step_2.output.structured.titel}} och {{step_2.output.structured.datum}}",
      "Modellen skriver fälten varje körning i onödan."
    ],
    [
      suggestion("unread_result", ["step-2"], {}),
      "Inget senare steg läser stegets svar",
      "kan steget tas bort"
    ],
    [
      suggestion("relay_step", ["step-2", "step-1"], {
        source_step_order: 1,
        source_step_id: "step-1",
        readers: [{ step_order: 3, step_id: "step-3", sites: [] }]
      }),
      "Steget skickar bara vidare @[Sammanfatta](step:step-1)",
      "@[Granska](step:step-3) kan läsa @[Sammanfatta](step:step-1) direkt"
    ],
    [
      suggestion("relay_step", ["step-1"], { source_step_order: null, readers: [] }),
      "Steget skickar bara vidare det som skickas in",
      "det som skickas in direkt"
    ],
    [
      suggestion("per_item_prompt_read", ["step-3", "step-1"], {
        execution_mode: "item_map",
        producer_step_order: 1,
        producer_step_id: "step-1"
      }),
      "Svaret från @[Sammanfatta](step:step-1) skickas en gång per del",
      "Steget körs en gång för varje del"
    ],
    [
      suggestion("repeated_long_material", ["step-3", "step-2"], {
        earlier_step_order: 2,
        earlier_step_id: "step-2",
        shared_step_orders: [1],
        shares_run_input: false
      }),
      "Samma underlag bearbetas både här och i @[Skriv svar](step:step-2)",
      "bearbetar @[Sammanfatta](step:step-1) som långt underlag"
    ],
    [
      suggestion("unused_form_field", [], { field: "Diarienummer" }),
      "Formulärfältet ”Diarienummer” används inte",
      "fyller i det i onödan"
    ]
  ])("renders %#: %s", (item, title, explanation) => {
    const step = STEPS.find((candidate) => candidate.id === item.steps[0]);
    const text = suggestionText(item, t, step, STEPS);
    expect(text.title).toBe(title);
    expect(text.explanation).toContain(explanation);
    // Every code has English too.
    expect(suggestionText(item, tEn, step, STEPS).title).not.toBe(title);
  });
});

describe("where suggestions are shown", () => {
  it("groups them by the step they are about, the run form's apart", () => {
    const items = [
      suggestion("unread_result", ["step-2"], {}),
      suggestion("relay_step", ["step-2", "step-1"], { source_step_order: 1, readers: [] }),
      suggestion("unused_form_field", [], { field: "x" }),
      suggestion("unread_result", ["step-9"], {})
    ];
    const byStep = suggestionsByStep(shownSuggestions(items, STEPS));
    expect([...byStep.keys()]).toEqual(["step-2"]);
    expect(byStep.get("step-2")).toHaveLength(2);
    expect(flowSuggestions(items).map((item) => item.code)).toEqual(["unused_form_field"]);
  });
});

describe("suggestionRequest", () => {
  it("names the suggestion's steps as mentions, and none for the run form", () => {
    expect(suggestionRequest(duplicateRead([INPUT, PROMPT]), STEPS, t)).toBe(
      "Förklara förslaget ”Svaret från @[Sammanfatta](step:step-1) skickas två gånger” " +
        "(duplicate_read) och föreslå hur flödet kan ändras. " +
        "Steg: @[Skriv svar](step:step-2) @[Sammanfatta](step:step-1)"
    );
    expect(
      suggestionRequest(suggestion("unused_form_field", [], { field: "Diarienummer" }), STEPS, t)
    ).toBe(
      "Förklara förslaget ”Formulärfältet ”Diarienummer” används inte” (unused_form_field) " +
        "och föreslå hur flödet kan ändras."
    );
  });
});
