import { describe, expect, it } from "vitest";
import {
  collectTemplateStepReferenceOrders,
  collectUnresolvedTemplateTokens,
  collectInvalidStructuredOutputReferences,
  getInputTemplateSourceConflictStepOrders,
  remapStepOrderTemplateTokens,
  replaceExactTemplateToken,
  classifyVariable,
  parsePromptSegments,
  getChipClasses,
  type VariableClassificationContext
} from "./flowVariableTokens";

describe("replaceExactTemplateToken", () => {
  it("rewrites only exact friendly tokens", () => {
    const input = "Hej {{Namn på brukare}} och {{Personnummer}}";
    const output = replaceExactTemplateToken(input, "Namn på brukare", "Brukare");
    expect(output).toBe("Hej {{Brukare}} och {{Personnummer}}");
  });
});

describe("collectTemplateStepReferenceOrders", () => {
  it("extracts unique ordered step references from template text", () => {
    expect(
      collectTemplateStepReferenceOrders(
        "{{ step_3.output.text }} {{ step_1.output.structured.title }} {{step_3.output}}"
      )
    ).toEqual([1, 3]);
  });
});

describe("getInputTemplateSourceConflictStepOrders", () => {
  it("does not flag earlier explicit underlag refs on previous_step steps", () => {
    expect(
      getInputTemplateSourceConflictStepOrders({
        inputSource: "previous_step",
        stepOrder: 9,
        templateStepRefs: [1, 2, 8]
      })
    ).toBeNull();
  });

  it("still flags unavailable current or future refs", () => {
    expect(
      getInputTemplateSourceConflictStepOrders({
        inputSource: "previous_step",
        stepOrder: 4,
        templateStepRefs: [1, 4, 5]
      })
    ).toEqual([4, 5]);
  });

  it("flags step refs on flow_input steps", () => {
    expect(
      getInputTemplateSourceConflictStepOrders({
        inputSource: "flow_input",
        stepOrder: 4,
        templateStepRefs: [1, 2]
      })
    ).toEqual([1, 2]);
  });
});

describe("remapStepOrderTemplateTokens", () => {
  it("remaps step_n references after reorder", () => {
    const input = "Ta {{step_1.output.text}} och {{step_3.output.text}}";
    const remap = new Map<number, number>([
      [1, 2],
      [2, 1],
      [3, 3]
    ]);
    const result = remapStepOrderTemplateTokens(input, remap, new Set());
    expect(result.text).toBe("Ta {{step_2.output.text}} och {{step_3.output.text}}");
    expect(result.changed).toBe(true);
    expect(result.rewrittenDeletedReferences).toEqual([]);
  });

  it("marks deleted step references for manual repair", () => {
    const input = "Behåll {{step_1.output.text}} men ta bort {{step_2.output.text}}";
    const remap = new Map<number, number>([[1, 1]]);
    const result = remapStepOrderTemplateTokens(input, remap, new Set([2]));
    expect(result.text).toContain("{{step_2_deleted.output.text}}");
    expect(result.rewrittenDeletedReferences).toEqual([2]);
  });
});

describe("collectUnresolvedTemplateTokens", () => {
  it("accepts friendly and technical tokens, flags unknown aliases", () => {
    const input =
      "{{Namn på brukare}} {{flow_input.text}} {{step_1.output.text}} {{okänd_variabel}}";
    const unresolved = collectUnresolvedTemplateTokens(input, new Set(["Namn på brukare"]));
    expect(unresolved).toEqual(["okänd_variabel"]);
  });

  it("treats step_input.* as a resolved technical token on document-input steps", () => {
    const input = "{{step_input.text}} och {{step_input.file_ids}}";
    const unresolved = collectUnresolvedTemplateTokens(input, new Set());
    expect(unresolved).toEqual([]);
  });
});

describe("classifyVariable", () => {
  const baseContext: VariableClassificationContext = {
    knownFieldNames: new Set(["Namn", "Personnummer"]),
    knownStepNames: new Map([
      [1, "Sammanfattning"],
      [2, "Analys"]
    ]),
    stepOutputTypes: new Map([
      [1, "text"],
      [2, "json"]
    ]),
    transcriptionEnabled: true,
    currentStepOrder: 3
  };

  it("classifies form field names as 'field'", () => {
    expect(classifyVariable("Namn", baseContext)).toBe("field");
    expect(classifyVariable("Personnummer", baseContext)).toBe("field");
  });

  it("classifies system variables", () => {
    expect(classifyVariable("transkribering", baseContext)).toBe("system");
    expect(classifyVariable("föregående_steg", baseContext)).toBe("system");
    expect(classifyVariable("indata_text", baseContext)).toBe("system");
  });

  it("classifies step name aliases as 'step'", () => {
    expect(classifyVariable("Sammanfattning", baseContext)).toBe("step");
    expect(classifyVariable("Analys", baseContext)).toBe("step");
  });

  it("classifies valid structured step output as 'structured'", () => {
    expect(classifyVariable("step_2.output.structured.title", baseContext)).toBe("structured");
  });

  it("classifies non-json structured references as 'unknown'", () => {
    expect(classifyVariable("step_1.output.structured.title", baseContext)).toBe("unknown");
  });

  it("classifies step output references as 'step'", () => {
    expect(classifyVariable("step_1.output.text", baseContext)).toBe("step");
    expect(classifyVariable("step_2.output", baseContext)).toBe("step");
  });

  it("classifies flow_input references as 'technical'", () => {
    expect(classifyVariable("flow_input.text", baseContext)).toBe("technical");
    expect(classifyVariable("flow.input.text", baseContext)).toBe("technical");
  });

  it("classifies step_input.* references as 'technical'", () => {
    expect(classifyVariable("step_input.text", baseContext)).toBe("technical");
    expect(classifyVariable("step_input.file_ids", baseContext)).toBe("technical");
  });

  it("classifies unknown tokens as 'unknown'", () => {
    expect(classifyVariable("okänd_variabel", baseContext)).toBe("unknown");
  });

  it("does not match step names from the current or later steps", () => {
    const ctx: VariableClassificationContext = {
      ...baseContext,
      currentStepOrder: 1
    };
    // Step 1 ("Sammanfattning") is not before step 1, so should not match as step alias
    expect(classifyVariable("Sammanfattning", ctx)).toBe("unknown");
  });
});

describe("parsePromptSegments", () => {
  const context: VariableClassificationContext = {
    knownFieldNames: new Set(["Namn"]),
    knownStepNames: new Map(),
    stepOutputTypes: new Map(),
    transcriptionEnabled: true,
    currentStepOrder: 1
  };

  it("parses text and variables into segments", () => {
    const segments = parsePromptSegments("Hej {{Namn}}, detta är test", context);
    expect(segments).toHaveLength(3);
    expect(segments[0]).toEqual({ type: "text", value: "Hej " });
    expect(segments[1]).toEqual({
      type: "variable",
      value: "{{Namn}}",
      token: "Namn",
      category: "field"
    });
    expect(segments[2]).toEqual({ type: "text", value: ", detta är test" });
  });

  it("handles empty text", () => {
    expect(parsePromptSegments("", context)).toEqual([]);
  });
});

describe("collectInvalidStructuredOutputReferences", () => {
  it("flags structured references to non-json steps", () => {
    const issues = collectInvalidStructuredOutputReferences(
      "Hej {{step_1.output.structured.name}}",
      [
        { step_order: 1, output_type: "text" },
        { step_order: 2, output_type: "json" }
      ],
      3
    );

    expect(issues).toEqual([
      {
        token: "step_1.output.structured.name",
        stepOrder: 1,
        reason: "non_json_output"
      }
    ]);
  });

  it("flags structured references to the current or future step", () => {
    const issues = collectInvalidStructuredOutputReferences(
      "Hej {{step_2.output.structured.name}}",
      [
        { step_order: 1, output_type: "json" },
        { step_order: 2, output_type: "json" }
      ],
      2
    );

    expect(issues).toEqual([
      {
        token: "step_2.output.structured.name",
        stepOrder: 2,
        reason: "unavailable_step"
      }
    ]);
  });
});

describe("getChipClasses", () => {
  it("returns correct classes for each category", () => {
    expect(getChipClasses("field")).toContain("label-blue");
    expect(getChipClasses("field")).toContain("bg-label-dimmer");
    expect(getChipClasses("system")).toContain("label-amethyst");
    expect(getChipClasses("step")).toContain("label-green");
    expect(getChipClasses("structured")).toContain("label-amethyst");
    expect(getChipClasses("technical")).toContain("label-blue");
    expect(getChipClasses("unknown")).toContain("label-red");
  });
});
