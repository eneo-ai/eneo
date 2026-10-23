import { describe, expect, it } from "vitest";
import {
  effectiveReasoningEffort,
  reasoningEffortLabel,
  reasoningEffortOptions
} from "./reasoning-effort";

const t = (key: string) => `<${key}>`;

describe("reasoningEffortOptions", () => {
  it("lists the levels of a model that offers a choice", () => {
    expect(
      reasoningEffortOptions({
        supported_model_kwargs: {
          reasoning_effort: { supported: true, control: "select", options: ["low", "high"] }
        }
      })
    ).toEqual(["low", "high"]);
  });

  it("is empty without reasoning, with a slider control, or without a model", () => {
    expect(reasoningEffortOptions({ supported_model_kwargs: {} })).toEqual([]);
    expect(
      reasoningEffortOptions({
        supported_model_kwargs: { reasoning_effort: { supported: false, options: ["low"] } }
      })
    ).toEqual([]);
    expect(
      reasoningEffortOptions({
        supported_model_kwargs: { reasoning_effort: { supported: true, control: "slider" } }
      })
    ).toEqual([]);
    expect(reasoningEffortOptions(null)).toEqual([]);
    expect(reasoningEffortOptions(undefined)).toEqual([]);
  });
});

describe("effectiveReasoningEffort", () => {
  const options = ["low", "medium", "high"];

  it("prefers the stored level, then the policy default, when the model offers them", () => {
    expect(effectiveReasoningEffort({ stored: "high", policyDefault: "low", options })).toBe(
      "high"
    );
    expect(effectiveReasoningEffort({ stored: null, policyDefault: "low", options })).toBe("low");
    expect(effectiveReasoningEffort({ stored: "xhigh", policyDefault: "low", options })).toBe(
      "low"
    );
    expect(effectiveReasoningEffort({ stored: null, policyDefault: "max", options })).toBeNull();
    expect(
      effectiveReasoningEffort({ stored: undefined, policyDefault: undefined, options })
    ).toBeNull();
  });
});

describe("reasoningEffortLabel", () => {
  it("translates the known levels and shows others as written", () => {
    expect(reasoningEffortLabel("none", t)).toBe("<none>");
    expect(reasoningEffortLabel("minimal", t)).toBe("<parameter_option_minimal>");
    expect(reasoningEffortLabel("xhigh", t)).toBe("<parameter_option_extra_high>");
    expect(reasoningEffortLabel("max", t)).toBe("<parameter_option_maximum>");
    expect(reasoningEffortLabel("ultra_deep", t)).toBe("ultra deep");
  });
});
