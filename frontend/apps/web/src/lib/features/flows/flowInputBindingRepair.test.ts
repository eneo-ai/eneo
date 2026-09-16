import { EneoError, type FlowStep } from "@eneo/eneo-js";
import { assert, describe, expect, it } from "vitest";
import { parseServerValidationIdentity } from "./flowStepValidationMessages";
import type { FlowInputMaterialOption } from "./flowInputBindings";
import {
  findDanglingBindingReferences,
  replaceBindingReference,
  replacementToken,
  repairOptionsFor
} from "./flowInputBindingRepair";

function makeStep(inputBindings: FlowStep["input_bindings"]): FlowStep {
  return {
    id: "step-3",
    assistant_id: "assistant-3",
    step_order: 3,
    user_description: "Summary",
    input_source: "previous_step",
    input_type: "text",
    output_type: "text",
    output_mode: "pass_through",
    input_bindings: inputBindings
  };
}

describe("findDanglingBindingReferences", () => {
  it.each([
    {
      field: "input_bindings.question",
      reference: "step_9.output.structured.title",
      expected: [{ location: { kind: "question" }, token: "step_9.output.structured.title" }]
    },
    {
      field: "input_bindings.source_refs[1].step_ref",
      reference: "step_9",
      expected: [{ location: { kind: "source_ref", index: 1 }, token: "step_9" }]
    },
    { field: "input_bindings.source_refs[2].step_ref", reference: "step_9", expected: [] }
  ])("locates exactly the server binding at $field", ({ field, reference, expected }) => {
    const step = makeStep({
      question: "{{step_9.output.structured.title}} {{step_8}}",
      source_refs: [
        { step_ref: "step_1", output: "text" },
        { step_ref: "step_9", output: "text" }
      ]
    });
    expect(
      findDanglingBindingReferences(step, {
        code: "flow_input_binding_unknown_step_order",
        field,
        reference
      })
    ).toEqual(expected);
  });
});

it("finds every distinct deleted question token and source ref across tails", () => {
  const step = makeStep({
    question:
      "{{step_9_deleted}} {{ step_9_deleted.output.text }} {{step_9_deleted}} {{step_8_deleted.output.structured.title}} {{step_1}} {{step_9_deleted_extra}}",
    source_refs: [
      { step_ref: "step_1", output: "text" },
      { step_ref: "step_7_deleted", output: "structured", field_path: "title" }
    ]
  });
  expect(findDanglingBindingReferences(step, { code: "deleted-step-reference" })).toEqual([
    { location: { kind: "question" }, token: "step_9_deleted" },
    { location: { kind: "question" }, token: "step_9_deleted.output.text" },
    { location: { kind: "question" }, token: "step_8_deleted.output.structured.title" },
    { location: { kind: "source_ref", index: 1 }, token: "step_7_deleted" }
  ]);
  expect(findDanglingBindingReferences(step, { code: "unrelated" })).toEqual([]);
});

it("does not offer targets for invalid bindings", () => {
  const step = makeStep({ question: "{{step_9_deleted}}", unsupported: true });
  expect(findDanglingBindingReferences(step, { code: "deleted-step-reference" })).toEqual([]);
  expect(
    findDanglingBindingReferences(step, {
      code: "flow_input_binding_unknown_step_order",
      field: "input_bindings.question",
      reference: "step_9_deleted"
    })
  ).toEqual([]);
});

const textOption: FlowInputMaterialOption = {
  key: "step_1:text:*",
  stepRef: "step_1",
  sourceStepOrder: 1,
  sourceStepName: "Source",
  output: "text",
  fieldPath: null,
  schemaType: null,
  description: null
};
const fieldOption: FlowInputMaterialOption = {
  ...textOption,
  key: "step_1:structured:title",
  output: "structured",
  fieldPath: "title",
  schemaType: "string"
};

it.each([textOption, fieldOption])(
  "rewrites only the exact question token with $output output",
  (option) => {
    const step = makeStep({
      question:
        "Use {{step_9_deleted.output.text}} and {{ step_9_deleted.output.text }}; keep {{step_9_deleted.output.structured.title}}.",
      source_refs: [
        { step_ref: "step_8_deleted", output: "text", label: "  Keep spaces  ", field_path: null }
      ]
    });
    const before = JSON.stringify(step);
    const token = option.output === "text" ? "step_1" : "step_1.output.structured.title";
    expect(replacementToken(option)).toBe(token);
    const repaired = replaceBindingReference(
      step,
      { location: { kind: "question" }, token: "step_9_deleted.output.text" },
      option
    );
    expect(repaired).toEqual({
      ...step.input_bindings,
      question: `Use {{${token}}} and {{${token}}}; keep {{step_9_deleted.output.structured.title}}.`
    });
    expect(JSON.stringify(repaired?.source_refs)).toBe(
      JSON.stringify(step.input_bindings?.source_refs)
    );
    expect(JSON.stringify(step)).toBe(before);
  }
);

it("blocks question repair for invalid bindings or a token that is no longer present", () => {
  const target = { location: { kind: "question" as const }, token: "step_9_deleted" };
  expect(
    replaceBindingReference(
      makeStep({ question: "{{step_9_deleted}}", unsupported: true }),
      target,
      textOption
    )
  ).toBeNull();
  expect(
    replaceBindingReference(makeStep({ question: "{{step_1}}" }), target, textOption)
  ).toBeNull();
});

it.each([textOption, fieldOption])(
  "replaces only the indexed source ref with $output output",
  (option) => {
    const untouched = {
      step_ref: "step_2",
      output: "text",
      label: " Keep spaces ",
      field_path: null
    };
    const step = makeStep({
      question: " Keep {{step_9_deleted}} exactly. ",
      source_refs: [
        untouched,
        {
          step_ref: "step_9_deleted",
          output: "structured",
          field_path: "items",
          label: "Evidence",
          item_template: "{title}"
        }
      ]
    });
    const before = JSON.stringify(step);
    const repaired = replaceBindingReference(
      step,
      { location: { kind: "source_ref", index: 1 }, token: "step_9_deleted" },
      option
    );
    expect(repaired).toEqual({
      question: " Keep {{step_9_deleted}} exactly. ",
      source_refs: [
        untouched,
        option.output === "text"
          ? { step_ref: "step_1", output: "text", label: "Evidence" }
          : {
              step_ref: "step_1",
              output: "structured",
              field_path: "title",
              label: "Evidence"
            }
      ]
    });
    expect(JSON.stringify((repaired?.source_refs as unknown[])[0])).toBe(JSON.stringify(untouched));
    expect(JSON.stringify(step)).toBe(before);
  }
);

it("blocks missing or stale source refs without changing the step", () => {
  const step = makeStep({ source_refs: [{ step_ref: "step_1", output: "text" }] });
  const before = JSON.stringify(step);
  for (const index of [0, 1]) {
    expect(
      replaceBindingReference(
        step,
        { location: { kind: "source_ref", index }, token: "step_9_deleted" },
        textOption
      )
    ).toBeNull();
  }
  expect(JSON.stringify(step)).toBe(before);
});

it("offers earlier text outputs and explicit fields for a question, never whole structured output", () => {
  const step = makeStep(null);
  const options = repairOptionsFor(
    step,
    [
      step,
      { ...makeStep(null), id: "step-4", step_order: 4 },
      {
        ...makeStep(null),
        id: "step-2",
        step_order: 2,
        output_type: "json",
        output_contract: { type: "object", properties: { title: { type: "string" } } }
      },
      { ...makeStep(null), id: "step-1", step_order: 1 }
    ],
    { location: { kind: "question" }, token: "step_9" }
  );
  expect(options.map((option) => option.key)).toEqual(["step_1:text:*", "step_2:structured:title"]);
  expect(options.map(replacementToken)).toEqual(["step_1", "step_2.output.structured.title"]);
});

it("preserves the raw question's indentation and trailing newline", () => {
  const step = makeStep({ question: "  Use {{step_9_deleted}}\n" });
  expect(
    replaceBindingReference(
      step,
      {
        location: { kind: "question" },
        token: "step_9_deleted"
      },
      textOption
    )
  ).toEqual({ question: "  Use {{step_1}}\n" });
});

it.each([
  {
    field: "input_bindings.question",
    reference: "step_9.output.structured.title",
    bindings: { question: "Use {{step_9.output.structured.title}}" },
    target: { location: { kind: "question" }, token: "step_9.output.structured.title" }
  },
  {
    field: "input_bindings.source_refs[1].step_ref",
    reference: "step_9",
    bindings: {
      source_refs: [
        { step_ref: "step_1", output: "text" },
        { step_ref: "step_9", output: "text" }
      ]
    },
    target: { location: { kind: "source_ref", index: 1 }, token: "step_9" }
  }
])(
  "discovers the binding from the draft validator payload at $field",
  ({ field, reference, bindings, target }) => {
    const code = "flow_input_binding_future_step_reference";
    const error = new EneoError(
      "Input bindings may only reference outputs from earlier steps.",
      "RESPONSE",
      400,
      0,
      {
        message: "Input bindings may only reference outputs from earlier steps.",
        eneo_error_code: 0,
        code,
        context: { issue_code: code, step_order: 2, field, reference }
      }
    );
    const identity = parseServerValidationIdentity(error);
    assert(identity);
    expect(
      findDanglingBindingReferences({ ...makeStep(bindings), step_order: 2 }, identity)
    ).toEqual([target]);
  }
);

it("never offers an array field for a source ref, while a question token may take one", () => {
  const step = {
    ...makeStep({ source_refs: [{ step_ref: "step_9", output: "text" }] }),
    id: "step-3",
    step_order: 3,
    output_mode: "compose_text" as const
  };
  const steps: FlowStep[] = [
    {
      ...makeStep(null),
      id: "step-1",
      step_order: 1,
      output_type: "json",
      output_contract: {
        type: "object",
        properties: {
          title: { type: "string" },
          items: {
            type: "array",
            items: { type: "object", properties: { title: { type: "string" } } }
          },
          // The backend reads both of these as arrays too; the options owner
          // cannot name their type, so a source ref must not be offered them.
          maybe_items: { type: ["array", "null"], items: { type: "string" } },
          inferred_items: { items: { type: "string" } }
        }
      }
    },
    step
  ];
  const forRef = repairOptionsFor(step, steps, {
    location: { kind: "source_ref", index: 0 },
    token: "step_9"
  });
  expect(forRef.map((option) => option.key)).toEqual(["step_1:structured:title"]);
  const forQuestion = repairOptionsFor(step, steps, {
    location: { kind: "question" },
    token: "step_9"
  });
  expect(forQuestion.map((option) => option.key)).toContain("step_1:structured:items");
});

it("offers no source-ref repairs for an item template while keeping question options", () => {
  const step = {
    ...makeStep({
      source_refs: [
        { step_ref: "step_9", output: "structured", field_path: "items", item_template: "{title}" }
      ]
    }),
    output_mode: "compose_text" as const
  };
  const steps: FlowStep[] = [
    { ...makeStep(null), id: "step-1", step_order: 1 },
    {
      ...makeStep(null),
      id: "step-2",
      step_order: 2,
      output_type: "json",
      output_contract: {
        type: "object",
        properties: {
          title: { type: "string" },
          items: {
            type: "array",
            items: { type: "object", properties: { title: { type: "string" } } }
          }
        }
      }
    },
    step
  ];
  const target = { location: { kind: "source_ref" as const, index: 0 }, token: "step_9" };
  const options = repairOptionsFor(step, steps, target);
  expect(options).toEqual([]);
  expect(
    repairOptionsFor(step, steps, { location: { kind: "question" }, token: "step_9" }).map(
      (option) => option.key
    )
  ).toEqual(["step_1:text:*", "step_2:structured:title", "step_2:structured:items"]);
});

it("offers no source-ref repairs when the receiving step has an input contract", () => {
  const step = {
    ...makeStep({
      source_refs: [{ step_ref: "step_9", output: "structured", field_path: "title" }]
    }),
    input_type: "json" as const,
    input_contract: { type: "object", properties: { title: { type: "string" } } }
  };
  const steps: FlowStep[] = [
    { ...makeStep(null), id: "step-1", step_order: 1 },
    {
      ...makeStep(null),
      id: "step-2",
      step_order: 2,
      output_type: "json",
      output_contract: { type: "object", properties: { title: { type: "string" } } }
    },
    step
  ];
  expect(
    repairOptionsFor(step, steps, { location: { kind: "source_ref", index: 0 }, token: "step_9" })
  ).toEqual([]);
  expect(
    repairOptionsFor(step, steps, { location: { kind: "question" }, token: "step_9" }).map(
      (option) => option.key
    )
  ).toEqual(["step_1:text:*", "step_2:structured:title"]);
});
