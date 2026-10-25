import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { makeStep } from "./flow-fixtures";
import {
  dismissedByText,
  flowSuggestions,
  flowSuggestionsQueryOptions,
  inSuggestionOrder,
  measuredBasisText,
  measuredImpactText,
  measuredSuggestionText,
  shownSuggestions,
  suggestionCount,
  suggestionRequest,
  suggestionsByStep,
  suggestionsOnPage,
  suggestionText,
  type FlowSuggestion,
  type FlowSuggestionImpact
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
      4,
      0
    ]);
    expect(flowSuggestionsQueryOptions("flow-1", 5).queryKey).not.toEqual(
      flowSuggestionsQueryOptions("flow-1", 4).queryKey
    );
  });

  it("keys a measured answer by its runs, and never reads it again by itself", () => {
    const plain = flowSuggestionsQueryOptions("flow-1", 4);
    const measured = flowSuggestionsQueryOptions("flow-1", 4, 10);
    expect(measured.queryKey).toEqual(["flows", "flow-1", "suggestions", 4, 10]);
    expect(measured.queryKey).not.toEqual(plain.queryKey);
    // Each measured read writes an audit entry: no focus, reconnect, remount
    // or retry reads it again, and it stays for the visit.
    expect(measured).toMatchObject({
      staleTime: Infinity,
      gcTime: Infinity,
      refetchOnMount: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: false
    });
    expect(plain.refetchOnWindowFocus).toBeUndefined();
  });
});

function measured(impact: Partial<FlowSuggestionImpact>): FlowSuggestionImpact {
  return {
    basis: "runs",
    level: "high",
    tokens_per_run: 1840,
    run_count: 8,
    version: 3,
    step_changed_since: false,
    ...impact
  };
}

describe("measuredImpactText", () => {
  it("says about what a run costs, over how many runs of which version", () => {
    expect(measuredImpactText(measured({}), t)).toBe(
      "Kostar cirka 1\u00a0800 tokens per körning, mätt i 8 körningar av version 3."
    );
    expect(measuredImpactText(measured({}), tEn)).toBe(
      "Costs about 1,800 tokens per run, measured in 8 runs of version 3."
    );
  });

  it("rounds to a number a person reads, and keeps a small one as it is", () => {
    expect(measuredImpactText(measured({ tokens_per_run: 123_456, run_count: 1 }), t)).toBe(
      "Kostar cirka 120\u00a0000 tokens per körning, mätt i 1 körning av version 3."
    );
    expect(measuredImpactText(measured({ tokens_per_run: 87 }), t)).toContain("cirka 87 tokens");
  });

  it("says when the step has changed since the runs it measured", () => {
    expect(measuredImpactText(measured({ step_changed_since: true }), t)).toBe(
      "Kostar cirka 1\u00a0800 tokens per körning, mätt i 8 körningar av version 3. " +
        "Steget har ändrats sedan dess."
    );
  });

  it("gives a finding without a token cost its run count only", () => {
    expect(measuredImpactText(measured({ tokens_per_run: null }), t)).toBe("Mätt i 8 körningar.");
  });

  it("says nothing for an impact judged from the definition", () => {
    expect(measuredImpactText({ basis: "definition", level: "high" }, t)).toBeNull();
  });
});

describe("measuredSuggestionText", () => {
  const overlaps = [
    { shared_share: 0.4, shared_bytes: 900, run_count: 5, held_runs: 3 },
    { shared_share: 0.62, shared_bytes: 3100, run_count: 5, held_runs: 4 }
  ];

  it("adds how much a duplicate's reads shared in the runs, the largest share only", () => {
    const item = {
      ...duplicateRead([INPUT, PROMPT]),
      params: { ...duplicateRead([INPUT, PROMPT]).params, measured_overlaps: overlaps },
      impact: measured({})
    };
    expect(measuredSuggestionText(item, t)).toBe(
      "Kostar cirka 1\u00a0800 tokens per körning, mätt i 8 körningar av version 3. " +
        "I 4 av de 5 senaste körningarna delade underlagen 62\u00a0% av texten."
    );
    expect(measuredSuggestionText(item, tEn)).toContain(
      "In 4 of the latest 5 runs, the inputs shared 62% of their text."
    );
  });

  it("says the overlap alone when the cost was not measured, and nothing without either", () => {
    const plain = duplicateRead([INPUT, PROMPT]);
    expect(
      measuredSuggestionText(
        { ...plain, params: { ...plain.params, measured_overlaps: [overlaps[0]] } },
        t
      )
    ).toBe("I 3 av de 5 senaste körningarna delade underlagen 40\u00a0% av texten.");
    expect(measuredSuggestionText(plain, t)).toBeNull();
  });
});

describe("measuredBasisText", () => {
  it("names the runs counted, and those left out because the person may not see them", () => {
    expect(measuredBasisText({ requested: 10, counted: 8, left_out: 0 }, 3, t)).toBe(
      "Baserat på 8 körningar."
    );
    expect(measuredBasisText({ requested: 10, counted: 8, left_out: 2 }, 3, t)).toBe(
      "Baserat på 8 körningar. " +
        "2 körningar räknades inte med eftersom du inte har behörighet att se dem."
    );
    expect(measuredBasisText({ requested: 10, counted: 1, left_out: 1 }, 3, tEn)).toBe(
      "Based on 1 run. 1 run was left out because you may not see it."
    );
  });

  it("says when there are no finished runs to count yet, or no suggestion", () => {
    expect(measuredBasisText({ requested: 10, counted: 0, left_out: 0 }, 2, t)).toBe(
      "Det finns inga avslutade körningar att räkna med än."
    );
    expect(measuredBasisText({ requested: 10, counted: 0, left_out: 3 }, 2, t)).toBe(
      "3 körningar räknades inte med eftersom du inte har behörighet att se dem."
    );
    expect(measuredBasisText({ requested: 10, counted: 8, left_out: 0 }, 0, t)).toBe(
      "Inga förslag. Baserat på 8 körningar."
    );
  });
});

describe("inSuggestionOrder", () => {
  const item = (name: string, level: string, tokens?: number) => ({
    name,
    suggestion: {
      impact:
        tokens === undefined
          ? { basis: "definition", level }
          : { basis: "runs", level, tokens_per_run: tokens, run_count: 8, version: 3 }
    } as FlowSuggestion
  });

  it("puts a known cost first, the highest first, then the level, then the core's order", () => {
    const ordered = inSuggestionOrder([
      item("låg", "low"),
      item("hög", "high"),
      item("billig", "low", 200),
      item("medel", "medium"),
      item("dyr", "medium", 4000),
      item("hög igen", "high")
    ]);
    expect(ordered.map(({ name }) => name)).toEqual([
      "dyr",
      "billig",
      "hög",
      "hög igen",
      "medel",
      "låg"
    ]);
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
    ],
    [
      suggestion("identical_inputs", ["step-3", "step-1", "step-2"], {
        producer_step_ids: ["step-1", "step-2"],
        producer_step_orders: [1, 2],
        sites: ["input_source", "assistant_prompt:step_2.output.text"],
        byte_size: 2048,
        observed_runs: 6,
        step_runs: 8
      }),
      "Steget får samma text från @[Sammanfatta](step:step-1) och @[Skriv svar](step:step-2)",
      "I 6 av de 8 senaste körningarna fick steget exakt samma text som indata " +
        "(föregående steg) och i prompten ({{step_2.output.text}}), fast den läses från två olika steg"
    ],
    [
      suggestion("identical_inputs", ["step-3", "step-1", "step-2"], {
        producer_step_ids: ["step-1", "step-2"],
        producer_step_orders: [1, 2],
        sites: ["input_bindings.question", "input_bindings.source_refs[0]"],
        observed_runs: 1,
        step_runs: 1
      }),
      "Steget får samma text från @[Sammanfatta](step:step-1) och @[Skriv svar](step:step-2)",
      "I den senaste körningen fick steget exakt samma text i frågan och i källhänvisning 1"
    ],
    [
      suggestion("context_headroom", ["step-2"], {
        peak_input_tokens: 117_000,
        token_limit: 128_000,
        limit_share: 0.91,
        inline_cap_failures: 0,
        duplicated_tokens_per_run: 30_000,
        duplicated_share: 0.26,
        related_fingerprints: [],
        step_runs: 8
      }),
      "Steget är nära modellens gräns för hur mycket text den tar emot",
      "Som mest fick modellen 91\u00a0% av vad den kan ta emot. " +
        "Ungefär 26\u00a0% av det är text som steget får två gånger. Skicka mindre till steget"
    ],
    [
      suggestion("context_headroom", ["step-2"], {
        peak_input_tokens: null,
        token_limit: 128_000,
        limit_share: null,
        inline_cap_failures: 2,
        duplicated_share: null,
        step_runs: 8
      }),
      "Underlaget har varit för stort för steget",
      "2 gånger misslyckades steget för att underlaget var för stort. Skicka mindre"
    ],
    [
      suggestion("format_fallback", ["step-2"], { fallback_runs: 5, step_runs: 8 }),
      "Steget behöver ofta två anrop till modellen",
      "I 5 av de 8 senaste körningarna klarade modellen inte att svara i fast format"
    ],
    [
      suggestion("model_relay", ["step-2", "step-1", "step-3"], {
        producer_step_order: 1,
        producer_step_id: "step-1",
        reads: [{ channel: "input", site: "input_source", selector: [] }],
        readers: [{ step_order: 3, step_id: "step-3", sites: ["input_source"] }],
        copied_share: 0.83,
        input_share: 0.9,
        copied_bytes: 5400,
        run_count: 5,
        held_runs: 4
      }),
      "Modellen skriver av svaret från @[Sammanfatta](step:step-1) ord för ord",
      "I 4 av de 5 senaste körningarna var 83\u00a0% av stegets svar texten från " +
        "@[Sammanfatta](step:step-1), avskriven ord för ord. Kopian läses av " +
        "@[Granska](step:step-3), som kan läsa @[Sammanfatta](step:step-1) direkt i stället."
    ],
    [
      suggestion("overlapping_inputs", ["step-3", "step-1", "step-2"], {
        inputs: [
          { step_order: 1, step_id: "step-1", sites: ["assistant_prompt:step_1.output.text"] },
          { step_order: 2, step_id: "step-2", sites: ["input_source"] }
        ],
        shared_bytes: 3100,
        shared_share: 0.62,
        run_count: 5,
        held_runs: 5
      }),
      "Svaren från @[Sammanfatta](step:step-1) och @[Skriv svar](step:step-2) har mycket text gemensamt",
      "I 5 av de 5 senaste körningarna hade svaret från @[Sammanfatta](step:step-1) i prompten " +
        "({{step_1.output.text}}) och svaret från @[Skriv svar](step:step-2) som indata " +
        "(föregående steg) 62\u00a0% av texten gemensamt"
    ],
    [
      suggestion("deterministic_candidate", ["step-2"], {
        output_verbatim_ratio: 0.96,
        own_bytes: 180,
        input_share: 0.97,
        run_count: 4,
        held_runs: 3
      }),
      "Modellen sätter bara ihop texten som steget får",
      "I 3 av de 4 senaste körningarna var 96\u00a0% av stegets svar hämtat ord för ord ur " +
        "underlaget, med bara lite egen text. Ett steg av typen ”Sätt ihop text utan AI” kan " +
        "göra samma sak utan modell"
    ],
    [
      suggestion("oversized_reasoning", ["step-2"], {
        reasoning_effort: "high",
        peak_input_tokens: 3800,
        peak_output_tokens: 900,
        token_limit: 128_000,
        limit_share: 0.03,
        run_count: 5,
        held_runs: 4
      }),
      "Steget ber om resonemangsnivån ”Hög” för ett litet svar i fast format",
      "I 4 av de 5 senaste körningarna var stegets anrop små: modellen fick som mest " +
        "3\u00a0% av vad den kan ta emot och skrev som mest 900 tokens, resonemanget " +
        "inräknat. Att plocka ut ett litet svar i fast format kräver sällan så mycket " +
        "resonemang, så en lägre nivå gör troligen samma arbete för mindre."
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

describe("oversized_reasoning", () => {
  const params = {
    reasoning_effort: "xhigh",
    peak_input_tokens: 400,
    peak_output_tokens: 3400,
    token_limit: 200_000,
    limit_share: 0,
    run_count: 1,
    held_runs: 1
  };

  it("names the effort as the editor does, a share under 1 % as such, and one run as the latest", () => {
    const text = suggestionText(
      suggestion("oversized_reasoning", ["step-2"], params),
      t,
      STEPS[1],
      STEPS
    );
    expect(text.title).toBe(
      "Steget ber om resonemangsnivån ”Extra hög” för ett litet svar i fast format"
    );
    expect(text.explanation).toContain(
      "I den senaste körningen var stegets anrop små: modellen fick som mest under 1\u00a0% av vad " +
        "den kan ta emot och skrev som mest 3\u00a0400 tokens, resonemanget inräknat."
    );
    expect(text.explanation).toContain("Det är bara ett råd");
    // Plain words: no field names, no model, no price.
    expect(`${text.title} ${text.explanation}`).not.toMatch(/reasoning_effort|token_limit|_/);
  });

  it("renders in English too", () => {
    const text = suggestionText(
      suggestion("oversized_reasoning", ["step-2"], {
        ...params,
        reasoning_effort: "high",
        limit_share: 0.03,
        run_count: 5,
        held_runs: 4
      }),
      tEn,
      STEPS[1],
      STEPS
    );
    expect(text.title).toBe(
      "The step asks for the reasoning effort “High” for a small answer in a fixed format"
    );
    expect(text.explanation).toContain(
      "In 4 of the latest 5 runs, the step's calls were small: the model got at most 3% of " +
        "what it can take in and wrote at most 3,400 tokens, its reasoning included."
    );
  });
});

describe("suggestionsOnPage", () => {
  const dismissed = (item: FlowSuggestion): FlowSuggestion => ({
    ...item,
    dismissed: { dismissed_by: "user-1", dismissed_at: "2026-10-25T09:30:00Z" }
  });

  it("keeps the dismissed suggestions apart, so they count nowhere", () => {
    const items = [
      suggestion("unread_result", ["step-2"], {}),
      dismissed(suggestion("relay_step", ["step-2", "step-1"], { source_step_order: 1 })),
      suggestion("unused_form_field", [], { field: "x" }),
      dismissed(suggestion("unused_form_field", [], { field: "y" })),
      // About a step the draft no longer has: shown nowhere, dismissed or not.
      dismissed(suggestion("unread_result", ["step-9"], {}))
    ];
    const page = suggestionsOnPage(items, STEPS);
    expect(page.shown.map(({ suggestion: item }) => item.code)).toEqual(["unread_result"]);
    expect(page.form.map((item) => item.params.field)).toEqual(["x"]);
    expect(
      page.dismissed.map(({ suggestion: item, step }) => [item.code, step?.id ?? null])
    ).toEqual([
      ["relay_step", "step-2"],
      ["unused_form_field", null]
    ]);
    expect(suggestionCount(page)).toBe(2);
    expect(suggestionCount(suggestionsOnPage(undefined, STEPS))).toBe(0);
  });

  it("says who dismissed one: the person reading, someone else, or a user who is gone", () => {
    expect(dismissedByText({ dismissed_by: "user-1" }, "user-1", t)).toBe("Ignorerat av dig");
    expect(dismissedByText({ dismissed_by: "user-2" }, "user-1", t)).toBe(
      "Ignorerat av en annan person"
    );
    expect(dismissedByText({ dismissed_by: null }, "user-1", tEn)).toBe(
      "Ignored by a user who no longer exists"
    );
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
