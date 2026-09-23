import { describe, expect, it } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";

import { buildContext } from "./components/flowPromptVariables";
import {
  getStepMaterial,
  getStepSourceLine,
  groupStepSources,
  ownTextIncludesUpload,
  type StepSourceLine
} from "./flowStepMaterial";

function step(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-2",
    assistant_id: "assistant-2",
    step_order: 2,
    user_description: "Skriv",
    input_source: "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  };
}

describe("flowStepMaterial", () => {
  it("counts only a whole reference to a known upload key as reading the upload", () => {
    expect(ownTextIncludesUpload("Transkript: {{step_input.text}}")).toBe(true);
    expect(ownTextIncludesUpload("Transkript: {{ step_input.text }}")).toBe(true);
    expect(ownTextIncludesUpload("Filer: {{step_input.file_ids}}")).toBe(true);
    expect(ownTextIncludesUpload("Transkript: {{step_input.text")).toBe(false);
    expect(ownTextIncludesUpload("Transkript: {{step_input.typo}}")).toBe(false);
    expect(ownTextIncludesUpload("Första filen: {{step_input.file_ids.0}}")).toBe(true);
    expect(ownTextIncludesUpload("Rubrik: {{step_input.text.rubrik}}")).toBe(false);
    expect(ownTextIncludesUpload("Transkript: {{step_input.text.}}")).toBe(false);
    expect(ownTextIncludesUpload("Filer: {{step_input.file_ids..0}}")).toBe(false);
    expect(ownTextIncludesUpload("Namn: {{flow_input.namn}}")).toBe(false);
  });

  it("follows the runtime order: own text, then chosen results, then the source", () => {
    const upload = { runtime_input: { enabled: true, input_format: "document" } };
    expect(getStepMaterial(step({ input_config: upload }), null)).toEqual({ kind: "upload" });
    expect(
      getStepMaterial(
        step({
          input_config: upload,
          input_bindings: { question: "{{step_input.typo}}" } as never
        }),
        null
      )
    ).toMatchObject({ kind: "own_text", withUpload: false });
    expect(
      getStepMaterial(
        step({
          input_bindings: { source_refs: [{ step_ref: "step_1", output: "text" }] } as never
        }),
        null
      )
    ).toEqual({ kind: "sources" });
    expect(getStepMaterial(step(), { step_order: 1, user_description: "Läs" })).toEqual({
      kind: "previous_step",
      stepOrder: 1,
      stepName: "Läs"
    });
  });
});

describe("getStepSourceLine", () => {
  const upload = { runtime_input: { enabled: true, input_format: "document" } };
  const formSchema = { fields: [{ name: "namn", label: "Brukarens namn", type: "text" }] };
  const contextFor = (current: FlowStep) =>
    buildContext([current], formSchema, false, current.step_order);
  const reads = (...parts: string[]) =>
    m.flow_step_reads({
      what: new Intl.ListFormat(getLocale(), { type: "conjunction" }).format(parts)
    });

  it("marks the step that takes in the upload and the form", () => {
    const first = step({
      step_order: 1,
      input_source: "flow_input",
      input_config: upload,
      input_bindings: { question: "Transkript: {{step_input.text}}\nNamn: {{flow_input.namn}}" }
    } as never);
    expect(getStepSourceLine(first, null, contextFor(first))).toEqual({
      text: reads(m.flow_step_reads_upload(), m.flow_step_reads_form()),
      readsRunInput: true,
      readsOnlyPreviousStep: false
    });
  });

  it("names up to two earlier steps and counts more", () => {
    const third = step({
      step_order: 3,
      input_bindings: { question: "{{step_1.output.text}}" } as never
    });
    expect(getStepSourceLine(third, null, contextFor(third))).toEqual({
      text: reads(m.flow_step_reads_step({ step: 1 })),
      readsRunInput: false,
      readsOnlyPreviousStep: false
    });
    const fifth = step({
      step_order: 5,
      input_bindings: {
        question: "{{step_1.output.text}} {{step_2.output.text}} {{step_4.output.text}}"
      } as never
    });
    expect(getStepSourceLine(fifth, null, contextFor(fifth))?.text).toBe(
      reads(m.flow_step_reads_steps({ count: 3 }))
    );
  });

  it("keeps the step before quiet and names what a default source reads", () => {
    const second = step();
    expect(
      getStepSourceLine(second, { step_order: 1, user_description: "Läs" }, contextFor(second))
    ).toEqual({
      text: reads(m.flow_step_reads_step({ step: 1 })),
      readsRunInput: false,
      readsOnlyPreviousStep: true
    });
    const start = step({ step_order: 1, input_source: "flow_input" });
    expect(getStepSourceLine(start, null, contextFor(start))).toMatchObject({
      text: reads(m.flow_step_reads_flow_input()),
      readsRunInput: true
    });
    const web = step({ input_source: "http_get" });
    expect(getStepSourceLine(web, null, contextFor(web))?.text).toBe(
      reads(m.flow_step_reads_web())
    );
  });

  it("counts the flow's input aliases as its input, and fixed text as the step's own", () => {
    const alias = step({ input_bindings: { question: "Text: {{indata_text}}" } as never });
    expect(getStepSourceLine(alias, null, contextFor(alias))).toMatchObject({
      text: reads(m.flow_step_reads_flow_input()),
      readsRunInput: true
    });
    const fixed = step({ input_bindings: { question: "Skriv en hälsning." } as never });
    expect(getStepSourceLine(fixed, null, contextFor(fixed))?.text).toBe(
      m.flow_step_reads_own_text()
    );
  });
});

describe("groupStepSources", () => {
  const line = (text: string, extra: Partial<StepSourceLine> = {}): StepSourceLine => ({
    text,
    readsRunInput: false,
    readsOnlyPreviousStep: false,
    ...extra
  });

  it("captions a run once and every step in it points at that caption", () => {
    expect(
      groupStepSources([
        line("Läser det uppladdade underlaget", { readsRunInput: true }),
        line("Läser steg 1", { readsOnlyPreviousStep: true }),
        line("Läser steg 1"),
        line("Läser steg 1"),
        line("Läser 3 tidigare steg")
      ])
    ).toEqual([0, 1, 1, 1, 4]);
  });

  it("keeps a plain step-by-step flow quiet", () => {
    expect(
      groupStepSources([
        line("Läser flödets indata", { readsRunInput: true }),
        line("Läser steg 1", { readsOnlyPreviousStep: true }),
        line("Läser steg 2", { readsOnlyPreviousStep: true })
      ])
    ).toEqual([0, null, null]);
  });

  it("starts over after a step without a source line", () => {
    expect(groupStepSources([line("Läser steg 1"), null, line("Läser steg 1")])).toEqual([
      0,
      null,
      2
    ]);
  });
});
