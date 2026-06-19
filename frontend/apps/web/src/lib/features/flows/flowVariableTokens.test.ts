import { describe, expect, it } from "vitest";
import {
  collectTemplateStepReferenceOrders,
  analyzeTemplateTokens,
  collectTemplateValidationIssues,
  getInputTemplateSourceConflictStepOrders,
  remapStepOrderTemplateTokens,
  replaceExactTemplateToken,
  classifyVariable,
  parsePromptSegments,
  getChipClasses,
  type VariableClassificationContext
} from "./flowVariableTokens";

function collectInvalidTokens(text: string, context: VariableClassificationContext): string[] {
  return analyzeTemplateTokens(text, context)
    .filter((analysis) => analysis.kind === "invalid")
    .map((analysis) => analysis.token);
}

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

describe("analyzeTemplateTokens invalid tokens", () => {
  const context: VariableClassificationContext = {
    knownFieldNames: new Set(["datum"]),
    knownStepNames: new Map([[1, "Sammanfattning"]]),
    stepOutputTypes: new Map([[1, "text"]]),
    transcriptionEnabled: true,
    currentStepOrder: 2
  };

  it("accepts friendly and technical tokens, flags unknown aliases", () => {
    const input =
      "{{Namn på brukare}} {{flow_input.text}} {{step_1.output.text}} {{okänd_variabel}}";
    const unresolved = collectInvalidTokens(input, {
      ...context,
      knownFieldNames: new Set(["Namn på brukare"])
    });
    expect(unresolved).toEqual(["okänd_variabel"]);
  });

  it("treats step_input.* as a resolved technical token on document-input steps", () => {
    const input = "{{step_input.text}} och {{step_input.file_ids}}";
    const unresolved = collectInvalidTokens(input, context);
    expect(unresolved).toEqual([]);
  });

  it("flags misspelled single-segment flow_input form field references", () => {
    const input = "{{flow_input.datm}}";
    const unresolved = collectInvalidTokens(input, context);
    expect(unresolved).toEqual(["flow_input.datm"]);
    expect(classifyVariable("flow_input.datm", context)).toBe("unknown");
  });

  it("keeps primary flow_input keys and JSON-shaped paths resolved", () => {
    const input = "{{flow_input.text}} {{flow_input.customer.id}} {{flow_input.datm.foo}}";
    const unresolved = collectInvalidTokens(input, context);
    expect(unresolved).toEqual([]);
    expect(classifyVariable("flow_input.text", context)).toBe("technical");
    expect(classifyVariable("flow_input.customer.id", context)).toBe("technical");
    expect(classifyVariable("flow_input.datm.foo", context)).toBe("technical");
  });

  it("flags removed top-level flow_input file ids", () => {
    const input = "{{flow_input.file_ids}} {{flow_input.file_ids.0}}";
    const unresolved = collectInvalidTokens(input, context);
    expect(unresolved).toEqual(["flow_input.file_ids", "flow_input.file_ids.0"]);
    expect(classifyVariable("flow_input.file_ids", context)).toBe("unknown");
    expect(classifyVariable("flow_input.file_ids.0", context)).toBe("unknown");
  });

  it("flags bare or empty flow_input references as unresolved", () => {
    const unresolved = collectInvalidTokens("{{flow_input}} {{flow_input.}}", context);

    expect(unresolved).toEqual(["flow_input", "flow_input."]);
    expect(classifyVariable("flow_input", context)).toBe("unknown");
    expect(classifyVariable("flow_input.", context)).toBe("unknown");
  });

  it("does not apply form-field typo detection to step_input paths", () => {
    const unresolved = collectInvalidTokens("{{step_input.datm}}", context);

    expect(unresolved).toEqual([]);
    expect(classifyVariable("step_input.datm", context)).toBe("technical");
  });

  it("does not flag unknown single-segment flow_input references when no form fields are declared", () => {
    const input = "{{flow_input.unknown}}";
    const unresolved = collectInvalidTokens(input, {
      ...context,
      knownFieldNames: new Set()
    });
    expect(unresolved).toEqual([]);
  });

  it("keeps chip classification and unresolved collection coherent", () => {
    const tokens = [
      "flow_input.datm",
      "flow_input.datum",
      "flow_input.text",
      "flow_input.customer.id",
      "flow_input",
      "flow_input.",
      "step_input.text",
      "step_1.output.text",
      "okänd_variabel"
    ];

    for (const token of tokens) {
      const unresolved = collectInvalidTokens(`{{${token}}}`, context);
      expect(unresolved.length > 0).toBe(classifyVariable(token, context) === "unknown");
    }
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
    expect(classifyVariable("flow_input.Namn", baseContext)).toBe("field");
  });

  it("classifies bare shadowed form field names as system variables", () => {
    const context: VariableClassificationContext = {
      ...baseContext,
      knownFieldNames: new Set(["datum"])
    };

    expect(classifyVariable("datum", context)).toBe("system");
    expect(classifyVariable("flow_input.datum", context)).toBe("field");
  });

  it("classifies system variables", () => {
    expect(classifyVariable("transkribering", baseContext)).toBe("system");
    expect(classifyVariable("föregående_steg", baseContext)).toBe("system");
    expect(classifyVariable("indata_text", baseContext)).toBe("system");
  });

  it("keeps bare system variables classified as system even when a form field has the same name", () => {
    const context = {
      ...baseContext,
      knownFieldNames: new Set(["datum"])
    };

    expect(classifyVariable("datum", context)).toBe("system");
    expect(classifyVariable("flow_input.datum", context)).toBe("field");
  });

  it("classifies step name aliases as 'step'", () => {
    expect(classifyVariable("Sammanfattning", baseContext)).toBe("step");
    expect(classifyVariable("Analys", baseContext)).toBe("step");
  });

  it("treats step_N tokens as step order references before matching step names", () => {
    const context: VariableClassificationContext = {
      ...baseContext,
      knownStepNames: new Map([[3, "step_2"]]),
      stepOutputTypes: new Map([[3, "text"]]),
      currentStepOrder: 4
    };

    expect(classifyVariable("step_2", context)).toBe("unknown");
    expect(analyzeTemplateTokens("{{step_2}}", context)).toEqual([
      {
        token: "step_2",
        kind: "invalid",
        category: "unknown",
        reason: "unavailable_step",
        stepOrder: 2
      }
    ]);
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

  it("classifies current, future, and missing step references as unknown", () => {
    expect(classifyVariable("step_3.output.text", baseContext)).toBe("unknown");
    expect(classifyVariable("step_4.output.text", baseContext)).toBe("unknown");
    expect(classifyVariable("step_99.output.text", baseContext)).toBe("unknown");
  });

  it("classifies deleted step marker references as unknown", () => {
    expect(classifyVariable("step_2_deleted.output.text", baseContext)).toBe("unknown");
  });

  it("classifies non-field flow_input references as 'technical'", () => {
    expect(classifyVariable("flow_input.text", baseContext)).toBe("technical");
    expect(classifyVariable("flow.input.text", baseContext)).toBe("technical");
  });

  it("classifies unknown single-segment flow_input references as unknown when form fields exist", () => {
    const context = {
      ...baseContext,
      knownFieldNames: new Set(["datum"])
    };

    expect(classifyVariable("flow_input.datm", context)).toBe("unknown");
    expect(classifyVariable("flow_input.datm.extra", context)).toBe("technical");
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

describe("collectTemplateValidationIssues", () => {
  const context: VariableClassificationContext = {
    knownFieldNames: new Set(["Namn"]),
    knownStepNames: new Map([[1, "Sammanfattning"]]),
    stepOutputTypes: new Map([
      [1, "text"],
      [2, "json"]
    ]),
    transcriptionEnabled: true,
    currentStepOrder: 3
  };

  it("reports unknown variables with the exact token", () => {
    expect(collectTemplateValidationIssues("Hej {{okänd}}", context)).toEqual([
      {
        token: "okänd",
        reason: "unknown_variable"
      }
    ]);
  });

  it("reports unavailable generic step references instead of treating them as valid", () => {
    expect(
      collectTemplateValidationIssues(
        "{{step_3.output.text}} {{step_4.output.text}} {{step_99.output.text}}",
        context
      )
    ).toEqual([
      {
        token: "step_3.output.text",
        reason: "unavailable_step",
        stepOrder: 3
      },
      {
        token: "step_4.output.text",
        reason: "unavailable_step",
        stepOrder: 4
      },
      {
        token: "step_99.output.text",
        reason: "unavailable_step",
        stepOrder: 99
      }
    ]);
  });

  it("reports structured references to text-output steps with a specific reason", () => {
    expect(collectTemplateValidationIssues("{{step_1.output.structured.name}}", context)).toEqual([
      {
        token: "step_1.output.structured.name",
        reason: "non_json_output",
        stepOrder: 1
      }
    ]);
  });

  it("reports deleted step marker references with a specific reason", () => {
    expect(collectTemplateValidationIssues("{{step_2_deleted.output.text}}", context)).toEqual([
      {
        token: "step_2_deleted.output.text",
        reason: "deleted_step",
        stepOrder: 2
      }
    ]);
  });
});

describe("analyzeTemplateTokens", () => {
  const context: VariableClassificationContext = {
    knownFieldNames: new Set(["Rubrik"]),
    knownStepNames: new Map([[1, "Skapa utkast"]]),
    stepOutputTypes: new Map([
      [1, "text"],
      [2, "json"]
    ]),
    transcriptionEnabled: true,
    currentStepOrder: 3
  };

  it("returns one typed analysis per token for valid and invalid tokens", () => {
    expect(
      analyzeTemplateTokens(
        "{{Rubrik}} {{Skapa utkast}} {{step_2.output.structured.title}} {{step_9.output.text}}",
        context
      )
    ).toEqual([
      {
        token: "Rubrik",
        kind: "valid",
        category: "field"
      },
      {
        token: "Skapa utkast",
        kind: "valid",
        category: "step"
      },
      {
        token: "step_2.output.structured.title",
        kind: "valid",
        category: "structured"
      },
      {
        token: "step_9.output.text",
        kind: "invalid",
        category: "unknown",
        reason: "unavailable_step",
        stepOrder: 9
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
