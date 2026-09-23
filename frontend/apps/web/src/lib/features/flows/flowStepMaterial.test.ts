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
  const flow = [
    step({ id: "s1", step_order: 1, user_description: "Läs", input_source: "flow_input" }),
    step({ id: "s2", step_order: 2, user_description: "Bedöm" }),
    step({ id: "s3", step_order: 3, user_description: "Skriv" }),
    step({ id: "s4", step_order: 4, user_description: "Granska" }),
    step({ id: "s5", step_order: 5, user_description: "Sammanställ" })
  ];
  // The step under test takes its place in the flow, as in the editor.
  const lineFor = (current: FlowStep) => {
    const steps = flow.map((other) => (other.step_order === current.step_order ? current : other));
    return getStepSourceLine(
      current,
      steps.find((other) => other.step_order === current.step_order - 1) ?? null,
      buildContext(steps, formSchema, false, current.step_order)
    );
  };
  const list = (parts: string[]) =>
    new Intl.ListFormat(getLocale(), { type: "conjunction" }).format(parts);
  const reads = (...parts: string[]) => m.flow_step_reads({ what: list(parts) });
  const ownText = (order: number, question: string) =>
    step({ step_order: order, input_bindings: { question } as never });

  it("marks the step that takes in the upload and the form", () => {
    const first = step({
      step_order: 1,
      input_source: "flow_input",
      input_config: upload,
      input_bindings: { question: "Transkript: {{step_input.text}}\nNamn: {{flow_input.namn}}" }
    } as never);
    expect(lineFor(first)).toEqual({
      text: reads(m.flow_step_reads_upload(), m.flow_step_reads_form()),
      readsRunInput: true
    });
  });

  it("resolves every way to read an earlier step, and only earlier steps that exist", () => {
    expect(lineFor(ownText(3, "{{step_2.output.text}} {{Läs}}"))?.text).toBe(
      reads(m.flow_step_reads_steps_numbered({ steps: list(["1", "2"]) }))
    );
    expect(lineFor(ownText(3, "{{Läs}}"))?.text).toBe(reads(m.flow_step_reads_step({ step: 1 })));
    expect(lineFor(ownText(3, "{{föregående_steg}}"))?.text).toBe(
      reads(m.flow_step_reads_step({ step: 2 }))
    );
    expect(lineFor(ownText(2, "{{step_4.output.text}} {{step_9.output.text}}"))?.text).toBe(
      m.flow_step_reads_own_text()
    );
  });

  it("names up to three earlier steps and counts more", () => {
    expect(
      lineFor(
        ownText(
          5,
          "{{step_1.output.text}} {{step_2.output.text}} {{step_3.output.text}} {{step_4.output.text}}"
        )
      )?.text
    ).toBe(reads(m.flow_step_reads_steps({ count: 4 })));
    expect(lineFor(ownText(3, "{{flow_input.namn}} {{step_1.output.text}} {{Bedöm}}"))).toEqual({
      text: reads(
        m.flow_step_reads_form(),
        m.flow_step_reads_step({ step: 1 }),
        m.flow_step_reads_step({ step: 2 })
      ),
      readsRunInput: true
    });
  });

  it("says a default source in words", () => {
    expect(lineFor(step({ step_order: 2 }))).toEqual({
      text: reads(m.flow_step_reads_previous()),
      readsRunInput: false
    });
    expect(lineFor(step({ step_order: 1, input_source: "flow_input" }))).toEqual({
      text: reads(m.flow_step_reads_flow_input()),
      readsRunInput: true
    });
    expect(lineFor(step({ step_order: 2, input_source: "http_get" }))?.text).toBe(
      reads(m.flow_step_reads_web())
    );
  });

  it("counts the flow's input aliases as its input, and fixed text as the step's own", () => {
    expect(lineFor(ownText(2, "Text: {{indata_text}}"))).toEqual({
      text: reads(m.flow_step_reads_flow_input()),
      readsRunInput: true
    });
    expect(lineFor(ownText(2, "Skriv en hälsning."))?.text).toBe(m.flow_step_reads_own_text());
  });
});

describe("groupStepSources", () => {
  const line = (text: string, readsRunInput = false): StepSourceLine => ({ text, readsRunInput });

  it("captions a run once and every step in it points at that caption", () => {
    expect(
      groupStepSources([
        line("Läser det uppladdade underlaget", true),
        line("Läser steg 1"),
        line("Läser steg 1"),
        line("Läser 3 tidigare steg")
      ])
    ).toEqual([0, 1, 1, 3]);
  });

  it("puts a step-by-step chain under one caption", () => {
    expect(
      groupStepSources([
        line("Läser flödets indata", true),
        line("Läser föregående steg"),
        line("Läser föregående steg")
      ])
    ).toEqual([0, 1, 1]);
  });

  it("starts over after a step without a source line", () => {
    expect(groupStepSources([line("Läser steg 1"), null, line("Läser steg 1")])).toEqual([
      0,
      null,
      2
    ]);
  });
});
