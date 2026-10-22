import { describe, expect, it } from "vitest";
import { makeFlow, makeStep } from "../flow-fixtures";
import { optionToken, removedReads, repairedBindings, repairOptions } from "./reference-repair";

const contract = {
  type: "object",
  properties: { beslut: { type: "string" }, punkter: { type: "array" }, oklar: {} }
};

const flow = makeFlow({
  steps: [
    makeStep(1, { user_description: "Sammanfatta" }),
    makeStep(2, { user_description: "Bedöm", output_type: "json", output_contract: contract }),
    makeStep(3, {
      user_description: "Svara",
      input_bindings: {
        question: "Svara på {{ step_4_deleted.output.text }} med {{step_1.output.text}}",
        source_refs: [
          { step_ref: "step_4_deleted", output: "text", label: "Underlag" },
          { step_ref: "step_1", output: "text" }
        ]
      }
    })
  ]
});
const step = flow.steps[2]!;

describe("the repair of a read of a removed step", () => {
  it("finds the removed reads in the underlag's text and chosen results", () => {
    expect(removedReads(step, flow.steps)).toEqual([
      { location: "question", token: "step_4_deleted.output.text" },
      { location: "source_ref", index: 0, token: "step_4_deleted" }
    ]);
    expect(removedReads(flow.steps[0]!, flow.steps)).toEqual([]);
  });

  it("offers the earlier answers and fields, and no array or untyped field as a chosen result", () => {
    const [question, ref] = removedReads(step, flow.steps);
    expect(repairOptions(flow, step, question!).map(optionToken)).toEqual([
      "step_1.output.text",
      "step_2.output.structured.beslut",
      "step_2.output.structured.punkter",
      "step_2.output.structured.oklar"
    ]);
    expect(repairOptions(flow, step, ref!).map(optionToken)).toEqual([
      "step_1.output.text",
      "step_2.output.structured.beslut"
    ]);
    const contracted = { ...step, input_contract: { type: "object" } };
    expect(repairOptions(flow, contracted, ref!)).toEqual([]);
  });

  it("puts the chosen result in place of the removed read and keeps the rest", () => {
    const [question, ref] = removedReads(step, flow.steps);
    const [answer, field] = repairOptions(flow, step, ref!);

    expect(repairedBindings(step, question!, field!)).toEqual({
      question: "Svara på {{step_2.output.structured.beslut}} med {{step_1.output.text}}",
      source_refs: step.input_bindings!.source_refs
    });
    expect(repairedBindings(step, ref!, answer!)).toEqual({
      question: step.input_bindings!.question,
      source_refs: [
        { step_ref: "step_1", output: "text", label: "Underlag" },
        { step_ref: "step_1", output: "text" }
      ]
    });
    expect(repairedBindings(step, ref!, field!)?.source_refs).toEqual([
      { step_ref: "step_2", output: "structured", field_path: "beslut", label: "Underlag" },
      { step_ref: "step_1", output: "text" }
    ]);
  });

  it("repairs nothing that has changed since the read was found", () => {
    const [question, ref] = removedReads(step, flow.steps);
    const [answer] = repairOptions(flow, step, ref!);
    const fixed = { ...step, input_bindings: { question: "Klart", source_refs: [] } };
    expect(repairedBindings(fixed, question!, answer!)).toBeNull();
    expect(repairedBindings(fixed, ref!, answer!)).toBeNull();
  });
});
