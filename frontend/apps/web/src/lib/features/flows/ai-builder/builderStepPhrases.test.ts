import { describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import { contractFields, fieldDescription, fieldLabel, readsLabel } from "./builderStepPhrases";

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

  it("falls back to the input source when the material names no earlier step", () => {
    expect(readsLabel(readingFrom("step_d"), 2, numberOf)).toBe(m.ai_builder_reads_previous());
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
