import { expect, test } from "vitest";
import {
  filterSupportedModelKwargs,
  getModelSpecificKwargNames,
  shouldShowModelSpecificParametersInfo,
  supportsBehaviorPresets,
  type CompletionModelWithSupportedKwargs
} from "./ModelKwargCapabilities";

function model(
  supported_model_kwargs: CompletionModelWithSupportedKwargs["supported_model_kwargs"]
): CompletionModelWithSupportedKwargs {
  return { supported_model_kwargs };
}

test("behavior presets are available when the model supports temperature", () => {
  expect(
    supportsBehaviorPresets(
      model({
        temperature: { supported: true, control: "slider", minimum: 0, maximum: 2, step: 0.01 },
        reasoning_effort: { supported: false }
      })
    )
  ).toBe(true);
});

test("model-specific info appears only when presets are replaced by real controls", () => {
  expect(
    shouldShowModelSpecificParametersInfo(
      model({
        temperature: { supported: false },
        reasoning_effort: { supported: true, control: "select", options: ["low", "medium", "high"] }
      })
    )
  ).toBe(true);

  expect(
    shouldShowModelSpecificParametersInfo(
      model({
        temperature: { supported: false },
        reasoning_effort: { supported: false }
      })
    )
  ).toBe(false);
});

test("model settings ignores behavior-only temperature and returns advanced controls", () => {
  expect(
    getModelSpecificKwargNames(
      model({
        temperature: { supported: true, control: "slider", minimum: 0, maximum: 2, step: 0.01 },
        top_p: { supported: true, control: "slider", minimum: 0, maximum: 1, step: 0.01 },
        presence_penalty: {
          supported: true,
          control: "slider",
          minimum: -2,
          maximum: 2,
          step: 0.1
        },
        frequency_penalty: { supported: false },
        top_k: { supported: true, control: "slider", minimum: 1, step: 1 }
      })
    )
  ).toEqual(["top_p", "presence_penalty", "top_k"]);
});

test("unsupported model kwargs are removed before saving", () => {
  expect(
    filterSupportedModelKwargs(
      {
        temperature: 0.2,
        top_p: 0.8,
        reasoning_effort: "high",
        verbosity: "low"
      },
      model({
        temperature: { supported: false },
        top_p: { supported: false },
        reasoning_effort: { supported: true, control: "select", options: ["low", "high"] },
        verbosity: { supported: false }
      })
    )
  ).toEqual({ reasoning_effort: "high" });
});
