import { describe, it, expect } from "vitest";
import { buildContext, buildAvailableVariables } from "./flowPromptVariables";
import type { FlowStep } from "@eneo/eneo-js";

const step = (order: number, name: string | null, outputType = "text"): FlowStep =>
  ({ step_order: order, user_description: name, output_type: outputType }) as unknown as FlowStep;

describe("buildContext", () => {
  it("collects usable field names, named steps, and output types as plain collections", () => {
    const ctx = buildContext(
      [step(1, "Transkribera"), step(2, null, "json")],
      { fields: [{ name: "titel", type: "string" }] },
      true,
      3
    );
    expect(ctx.knownFieldNames).toBeInstanceOf(Set);
    expect(ctx.knownStepNames).toBeInstanceOf(Map);
    expect(ctx.knownFieldNames.has("titel")).toBe(true);
    expect(ctx.knownStepNames.get(1)).toBe("Transkribera");
    expect(ctx.knownStepNames.has(2)).toBe(false); // unnamed step skipped
    expect(ctx.stepOutputTypes.get(2)).toBe("json");
    expect(ctx.transcriptionEnabled).toBe(true);
    expect(ctx.currentStepOrder).toBe(3);
  });
});

describe("buildAvailableVariables", () => {
  const steps = [step(1, "Transkribera"), step(2, "Sammanfatta")];

  it("offers fields and step aliases but hides technical tokens outside advanced mode", () => {
    const ctx = buildContext(steps, { fields: [{ name: "titel", type: "string" }] }, false, 3);
    const basic = buildAvailableVariables(ctx, steps, false);
    expect(basic.some((v) => v.category === "field" && v.label === "titel")).toBe(true);
    expect(basic.some((v) => v.category === "step" && v.label === "Transkribera")).toBe(true);
    expect(basic.some((v) => v.token.startsWith("step_"))).toBe(false);
    expect(basic.some((v) => v.token === "föregående_steg")).toBe(false);
  });

  it("adds föregående_steg and step-output tokens in advanced mode", () => {
    const ctx = buildContext(steps, undefined, false, 3);
    const advanced = buildAvailableVariables(ctx, steps, true);
    expect(advanced.some((v) => v.token === "föregående_steg")).toBe(true);
    expect(advanced.some((v) => v.token === "step_1.output.text")).toBe(true);
    expect(advanced.some((v) => v.token === "step_2.output.text")).toBe(true);
  });
});
