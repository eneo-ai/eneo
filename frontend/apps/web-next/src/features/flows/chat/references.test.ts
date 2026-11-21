import { describe, expect, it } from "vitest";
import { makeFlow, makeStep } from "../flow-fixtures";
import {
  answerReference,
  parseReference,
  referenceChoices,
  referenceParts,
  referenceTone,
  referencesIn,
  stepMention,
  valueWhat
} from "./references";

const flow = makeFlow({
  steps: [
    makeStep(1, {
      user_description: "Extrahera",
      output_type: "json",
      output_contract: {
        type: "object",
        properties: { fastighet: { type: "string" }, atgard: { type: "string" } }
      }
    }),
    makeStep(2, { user_description: "Hämta register" }),
    makeStep(3, { user_description: "Bedömning" })
  ]
});

describe("referenceChoices", () => {
  it("offers every step, then the values it produces, in step order", () => {
    expect(
      referenceChoices(flow).map((choice) =>
        choice.kind !== "value" ? choice.raw : `${choice.raw} ${JSON.stringify(choice.what)}`
      )
    ).toEqual([
      "@[Extrahera](step:step-1)",
      '{{step_1.output.text}} {"type":"text"}',
      '{{step_1.output.structured}} {"type":"structured"}',
      '{{step_1.output.structured.fastighet}} {"type":"field","field":"fastighet"}',
      '{{step_1.output.structured.atgard}} {"type":"field","field":"atgard"}',
      "@[Hämta register](step:step-2)",
      '{{step_2.output.text}} {"type":"text"}',
      "@[Bedömning](step:step-3)",
      '{{step_3.output.text}} {"type":"text"}'
    ]);
  });

  it("keeps a step's name out of the mention's brackets", () => {
    expect(stepMention({ id: "s", user_description: "Läs [bilaga]" })).toBe(
      "@[Läs bilaga](step:s)"
    );
  });
});

describe("referenceParts", () => {
  it("splits a text into text, value references and step mentions", () => {
    const parts = referenceParts(
      "Låt @[Bedömning](step:step-3) läsa {{step_1.output.structured.atgard}} i stället.",
      flow
    );
    expect(parts.map((part) => part.kind)).toEqual(["text", "step", "text", "value", "text"]);
    const mention = parts[1];
    const value = parts[3];
    expect(mention?.kind === "step" && mention.step?.step_order).toBe(3);
    expect(value?.kind === "value" && value.meaning).toEqual({
      kind: "step_field",
      order: 1,
      field: "atgard"
    });
  });

  it("reads every step, not only the earlier ones, and names a removed one", () => {
    const last = parseReference("{{step_3.output.text}}", flow);
    expect(last && referenceTone(last)).toBe("reads");
    const gone = parseReference("{{step_9.output.text}}", flow);
    expect(gone && referenceTone(gone)).toBe("missing");
    const mention = parseReference("@[Borta](step:00000000-0000-4000-8000-000000000000)", flow);
    expect(mention?.kind).toBe("step");
    expect(mention && referenceTone(mention)).toBe("missing");
    const fields = parseReference("{{step_2.output.structured.x}}", flow);
    expect(fields && referenceTone(fields)).toBe("warning");
  });

  it("lists each reference once, in order of first appearance", () => {
    expect(
      referencesIn(
        "{{step_2.output.text}} och @[Extrahera](step:step-1), sedan {{step_2.output.text}} igen",
        flow
      ).map((reference) => reference.raw)
    ).toEqual(["{{step_2.output.text}}", "@[Extrahera](step:step-1)"]);
  });

  it("is not a reference when the text holds more than one, or none", () => {
    expect(parseReference("{{step_1.output.text}} x", flow)).toBeNull();
    expect(parseReference("hej", flow)).toBeNull();
  });
});

describe("answerReference", () => {
  it("reads a step's bare id as the step, and any other bare mention as its name", () => {
    const step = answerReference("@[Steg 3](step-3)", flow);
    expect(step?.kind === "step" && [step.raw, step.step?.step_order]).toEqual([
      "@[Steg 3](step:step-3)",
      3
    ]);
    expect(answerReference("@[Steg 9](nonsense)", flow)).toEqual({ kind: "text", text: "Steg 9" });
    // With the scheme, a step the flow no longer has is still a reference to it.
    const gone = answerReference("@[Borta](step:step-9)", flow);
    expect(gone?.kind === "step" && referenceTone(gone)).toBe("missing");
    expect(answerReference("@[sidan](https://example.com)", flow)).toBeNull();
  });
});

describe("valueWhat", () => {
  it("names a field, the text or the structured answer, and nothing for the run's own values", () => {
    expect(valueWhat({ kind: "step_field", order: 1, field: "atgard" })).toEqual({
      type: "field",
      field: "atgard"
    });
    expect(valueWhat({ kind: "step_answer", order: 1 })).toEqual({ type: "text" });
    expect(valueWhat({ kind: "date" })).toBeNull();
  });
});
