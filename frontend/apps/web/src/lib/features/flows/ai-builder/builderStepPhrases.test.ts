import { describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import { getLocale } from "$lib/paraglide/runtime";

import {
  contractFields,
  fieldDescription,
  fieldLabel,
  inSentence,
  readsLabel
} from "./builderStepPhrases";

const ORDER: Record<string, number> = { step_a: 1, step_b: 2, step_c: 3, step_d: 4 };
const numberOf = (ref: string) => ORDER[ref] ?? null;
const readingFrom = (...refs: string[]) => ({
  input_source: "previous_step" as const,
  input_bindings: { source_refs: refs.map((step_ref) => ({ step_ref, output: "text" })) }
});

describe("readsLabel", () => {
  it("names the steps a step reads, as a range when they run together", () => {
    expect(readsLabel(readingFrom("step_b", "step_a"), 3, numberOf)).toBe(
      m.ai_builder_reads_steps_two({ first: "1", second: "2" })
    );
    expect(readsLabel(readingFrom("step_c", "step_a", "step_b"), 4, numberOf)).toBe(
      m.ai_builder_reads_steps_range({ first: "1", last: "3" })
    );
    expect(readsLabel(readingFrom("step_a", "step_c"), 4, numberOf)).toBe(
      m.ai_builder_reads_steps_two({ first: "1", second: "3" })
    );
  });

  it("reads the step's own underlag before its input source", () => {
    const withQuestion = (question: string, refs: string[] = []) => ({
      input_source: "previous_step" as const,
      input_bindings: {
        question,
        ...(refs.length > 0
          ? { source_refs: refs.map((step_ref) => ({ step_ref, output: "text" })) }
          : {})
      }
    });
    // Its own text names step 1, so it does not read step 2, the previous step.
    expect(readsLabel(withQuestion("Sammanfatta {{ step_a.output.text }}."), 3, numberOf)).toBe(
      m.ai_builder_reads_step({ step: "1" })
    );
    // Chosen results and the flow input together, in one sentence.
    expect(readsLabel(withQuestion("Namn: {{ flow_input.namn }}", ["step_b"]), 3, numberOf)).toBe(
      new Intl.ListFormat(getLocale(), { type: "conjunction" }).format([
        m.ai_builder_reads_flow_input(),
        inSentence(m.ai_builder_reads_step({ step: "2" }), getLocale())
      ])
    );
    // The runtime's aliases: the previous step, the flow input and an upload.
    expect(readsLabel(withQuestion("Jämför {{ föregående_steg }}."), 3, numberOf)).toBe(
      m.ai_builder_reads_step({ step: "2" })
    );
    expect(readsLabel(withQuestion("Läs {{ indata_text }}."), 3, numberOf)).toBe(
      m.ai_builder_reads_flow_input()
    );
    expect(readsLabel(withQuestion("Namn: {{ flow.input.namn }}"), 3, numberOf)).toBe(
      m.ai_builder_reads_flow_input()
    );
    expect(readsLabel(withQuestion("Fil: {{ step_input.text }}"), 3, numberOf)).toBe(
      m.ai_builder_reads_upload()
    );
    // Fixed text only.
    expect(readsLabel(withQuestion("Läs policyn noga."), 3, numberOf)).toBe(
      m.ai_builder_reads_own_text()
    );
  });

  it("never falls back to the input source that explicit underlag replaces", () => {
    // A chosen result this review cannot place is still chosen material.
    expect(readsLabel(readingFrom("step_d"), 2, numberOf)).toBe(m.ai_builder_reads_chosen());
    expect(
      readsLabel(
        { input_source: "all_previous_steps", input_bindings: { question: "{{ okänd }}" } },
        3,
        numberOf
      )
    ).toBe(m.ai_builder_reads_chosen());
  });

  it("reads the input source when the step has no underlag of its own", () => {
    expect(
      readsLabel({ input_source: "all_previous_steps", input_bindings: null }, 3, numberOf)
    ).toBe(m.ai_builder_reads_steps_two({ first: "1", second: "2" }));
    expect(readsLabel({ input_source: "previous_step", input_bindings: null }, 1, numberOf)).toBe(
      m.ai_builder_reads_flow_input()
    );
  });
});

describe("contract fields", () => {
  it("lists fields in the order the required list asks for them", () => {
    const contract = {
      type: "object",
      properties: { rekommenderade_nasta_steg: {}, riskniva: {}, sammanfattning: {} },
      required: ["sammanfattning", "riskniva", "rekommenderade_nasta_steg"]
    };
    expect(contractFields(contract).map(([key]) => key)).toEqual([
      "sammanfattning",
      "riskniva",
      "rekommenderade_nasta_steg"
    ]);
  });

  it("spells a plain ASCII name the way its description does", () => {
    const risk = { description: "Bedömd risknivå (låg, medel eller hög)." };
    const next = { title: "Rekommenderade nasta steg", description: "Rekommenderade nästa steg." };
    expect(fieldLabel("riskniva", risk, "sv")).toBe("Risknivå");
    expect(fieldLabel("rekommenderade_nasta_steg", next, "sv")).toBe("Rekommenderade nästa steg");
    // A name that already has its letters keeps them.
    expect(fieldLabel("x", { title: "Åtgärd", description: "Atgard att vidta" }, "sv")).toBe(
      "Åtgärd"
    );
  });

  it("drops a description that only repeats the name", () => {
    const next = { description: "Rekommenderade nästa steg." };
    expect(fieldDescription("Rekommenderade nästa steg", next, "sv")).toBeNull();
    expect(fieldDescription("Risknivå", { description: "Låg, medel eller hög." }, "sv")).toBe(
      "Låg, medel eller hög."
    );
  });
});
