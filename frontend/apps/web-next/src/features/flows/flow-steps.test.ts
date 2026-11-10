import { describe, expect, it } from "vitest";
import { makeFlow, makeStep } from "./flow-fixtures";
import {
  orderWithMove,
  orderWithNewStep,
  orderWithout,
  readTarget,
  stepReaders,
  stepReads,
  stepsInOrder,
  templateParts,
  unclosedReference
} from "./flow-steps";

const ids = (slots: { step_id?: string | null }[] | null) => slots?.map((slot) => slot.step_id);

describe("stepReads", () => {
  const steps = [
    makeStep(1, { user_description: "Sammanfatta" }),
    makeStep(2, { user_description: "Granska" }),
    makeStep(3)
  ];

  it("follows the input source when the step has no bindings", () => {
    expect(stepReads(steps[0]!, steps)).toEqual([{ kind: "flow_input" }]);
    expect(stepReads(steps[1]!, steps)).toEqual([{ kind: "step", order: 1, step: steps[0] }]);
    expect(
      stepReads({ ...steps[2]!, input_source: "all_previous_steps" }, steps).map(
        (read) => read.kind === "step" && read.order
      )
    ).toEqual([1, 2]);
    expect(stepReads({ ...steps[2]!, input_source: "http_get" }, steps)).toEqual([
      { kind: "http" }
    ]);
  });

  it("reads what the bindings name instead, by alias, by name and as the previous step", () => {
    const reader = makeStep(3, {
      input_bindings: {
        question: "Jämför {{step_1.output.text}} med {{Granska}} och {{flow_input.diarienummer}}",
        source_refs: [{ step_ref: "step_2", output: "text" }]
      }
    });
    expect(stepReads(reader, [...steps.slice(0, 2), reader])).toEqual([
      { kind: "step", order: 1, step: steps[0] },
      { kind: "step", order: 2, step: steps[1] },
      { kind: "flow_input" }
    ]);
    const previous = makeStep(2, { input_bindings: { question: "{{föregående_steg}}" } });
    expect(stepReads(previous, steps)).toEqual([{ kind: "step", order: 1, step: steps[0] }]);
  });

  it("never reads itself or a later step, and shows a read of a removed step as missing", () => {
    const reader = makeStep(2, {
      input_bindings: { question: "{{step_2}} {{step_3}} {{step_1_deleted}}" }
    });
    expect(stepReads(reader, steps)).toEqual([{ kind: "step", order: 1, step: null }]);
  });

  it("reads a tool step's whole-reference arguments next to the tool", () => {
    const tool = makeStep(2, {
      input_source: "tool",
      input_config: { tool: { arguments: { query: "{{step_1.output.text}}", limit: 3 } } }
    });
    expect(stepReads(tool, steps)).toEqual([
      { kind: "step", order: 1, step: steps[0] },
      { kind: "tool" }
    ]);
  });
});

describe("stepReaders", () => {
  it("lists the later steps that name a step, not those that read the step before them", () => {
    const steps = [
      makeStep(1),
      makeStep(2),
      makeStep(3, { input_bindings: { question: "{{step_1}}" } })
    ];
    expect(stepReaders(steps[0]!, steps).map((step) => step.step_order)).toEqual([3]);
    expect(stepReaders(steps[1]!, steps)).toEqual([]);
  });

  it("counts a Word step whose field reads the step", () => {
    const steps = [
      makeStep(1),
      makeStep(2),
      makeStep(3, {
        output_mode: "template_fill",
        output_type: "docx",
        output_config: {
          placeholders: ["sammanfattning"],
          bindings: { sammanfattning: "{{step_1.output.text}}" }
        }
      })
    ];
    expect(stepReaders(steps[0]!, steps).map((step) => step.step_order)).toEqual([3]);
    expect(stepReads(steps[2]!, steps).map((read) => read.kind === "step" && read.order)).toEqual([
      1, 2
    ]);
  });

  it("counts an HTTP call or webhook whose address, body or header value reads the step", () => {
    const http = (order: number, overrides: Parameters<typeof makeStep>[1]) => [
      makeStep(1),
      makeStep(2),
      makeStep(order, overrides)
    ];
    const readers = (steps: ReturnType<typeof http>) =>
      stepReaders(steps[0]!, steps).map((step) => step.step_order);

    expect(
      readers(
        http(3, {
          input_source: "http_get",
          input_config: {
            url: "https://api.example.se/{{step_1.output.text}}",
            auth: { mode: "none" }
          }
        })
      )
    ).toEqual([3]);
    expect(
      readers(
        http(3, {
          output_mode: "http_post",
          output_config: {
            url: "https://hooks.example.se",
            auth: { mode: "none" },
            body: { mode: "json_template", template: '{"svar": "{{step_1.output.text}}"}' }
          }
        })
      )
    ).toEqual([3]);
    expect(
      readers(
        http(3, {
          output_mode: "http_post",
          output_config: {
            url: "https://hooks.example.se",
            auth: { mode: "none" },
            custom_headers: [{ name: "X-Fall", value: "{{step_1.output.text}}" }]
          }
        })
      )
    ).toEqual([3]);
    // A webhook config on a step that sends none reads nothing.
    expect(
      readers(
        http(3, {
          output_config: { url: "https://hooks.example.se/{{step_1.output.text}}" }
        })
      )
    ).toEqual([]);
  });
});

describe("step orders", () => {
  const flow = makeFlow({ steps: [makeStep(2), makeStep(1), makeStep(3)] });
  const steps = stepsInOrder(flow);

  it("sorts the steps in run order", () => {
    expect(steps.map((step) => step.step_order)).toEqual([1, 2, 3]);
  });

  it("moves a step one place, and refuses a move past either end", () => {
    expect(ids(orderWithMove(steps, "step-2", -1))).toEqual(["step-2", "step-1", "step-3"]);
    expect(ids(orderWithMove(steps, "step-2", 1))).toEqual(["step-1", "step-3", "step-2"]);
    expect(orderWithMove(steps, "step-1", -1)).toBeNull();
    expect(orderWithMove(steps, "step-3", 1)).toBeNull();
    expect(orderWithMove(steps, "unknown", 1)).toBeNull();
  });

  it("leaves a removed step out of the order", () => {
    expect(ids(orderWithout(steps, "step-2"))).toEqual(["step-1", "step-3"]);
  });

  it("places a new step at its position, clamped to the ends", () => {
    expect(orderWithNewStep(steps, 2)).toEqual([
      { step_id: "step-1" },
      { new_step: 0 },
      { step_id: "step-2" },
      { step_id: "step-3" }
    ]);
    expect(orderWithNewStep(steps, 1)[0]).toEqual({ new_step: 0 });
    expect(orderWithNewStep(steps, 9).at(-1)).toEqual({ new_step: 0 });
  });
});

describe("prompt reads", () => {
  const steps = [
    makeStep(1, { user_description: "Sammanfatta" }),
    makeStep(2, { user_description: "Granska" }),
    makeStep(3, { input_bindings: { question: "{{step_1}}" } })
  ];
  const prompts = new Map([["assistant-3", "Väg in {{Granska}} och {{step_4.output.text}}."]]);

  it("adds what the prompt reads to what the material reads", () => {
    expect(stepReads(steps[2]!, steps, prompts)).toEqual([
      { kind: "step", order: 1, step: steps[0] },
      { kind: "step", order: 2, step: steps[1] }
    ]);
    expect(stepReaders(steps[1]!, steps, prompts)).toEqual([steps[2]]);
    expect(stepReaders(steps[1]!, steps)).toEqual([]);
  });
});

describe("the reference grammar", () => {
  const steps = [makeStep(1, { user_description: "Sammanfatta" }), makeStep(2)];

  it("splits a template into its text and references", () => {
    expect(templateParts("{{a}} och {{ b }}")).toEqual([
      { kind: "read", token: "a", raw: "{{a}}" },
      { kind: "text", text: " och " },
      { kind: "read", token: "b", raw: "{{ b }}" }
    ]);
  });

  it("tells what one reference reads from where it stands", () => {
    expect(readTarget("step_1.output.text", steps[1]!, steps)).toEqual({
      kind: "step",
      order: 1,
      via: "alias"
    });
    expect(readTarget("Sammanfatta", steps[1]!, steps)).toEqual({
      kind: "step",
      order: 1,
      via: "name"
    });
    expect(readTarget("step_2", steps[1]!, steps)).toEqual({ kind: "not_earlier", order: 2 });
    expect(readTarget("föregående_steg", steps[0]!, steps)).toEqual({ kind: "flow_input" });
  });

  it("finds a reference that is opened and never closed", () => {
    expect(unclosedReference("Läs {{transkribering} och svara")).toBe("{{transkribering}");
    expect(unclosedReference("Läs {{ klammer.")).toBe("{{ klammer.");
    expect(unclosedReference("Läs {{step_1.output.text}} och {{datum}}")).toBeNull();
    expect(unclosedReference("{{step_1.output.text}} men {{")).toBe("{{");
    expect(unclosedReference("Inga hänvisningar alls")).toBeNull();
  });

  it("leaves out the reference being typed at the caret, not one before it", () => {
    expect(unclosedReference("Läs {{dat", 9)).toBeNull();
    expect(unclosedReference("Läs {{dat", 7)).toBeNull();
    expect(unclosedReference("Läs {{dat", 4)).toBe("{{dat");
    expect(unclosedReference("Läs {{dat och", 13)).toBe("{{dat");
    expect(unclosedReference("Läs {{a} och {{b", 16)).toBe("{{a}");
    expect(unclosedReference("Läs {{a} och {{b", 8)).toBe("{{b");
    expect(unclosedReference("{{step_1.output.text}} {{d", 26)).toBeNull();
  });
});
