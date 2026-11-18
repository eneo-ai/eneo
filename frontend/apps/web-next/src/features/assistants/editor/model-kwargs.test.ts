import { describe, expect, it } from "vitest";
import {
  behaviourFromKwargs,
  filterSupportedKwargs,
  firstInvalidNumericKwarg,
  isValidNumericKwarg,
  kwargsForBehaviour,
  modelSpecificKwargs,
  numericKwargRange,
  supportsBehaviorPresets
} from "./model-kwargs";
import { modelKwargFieldId } from "./model-kwargs-rows";

const model = {
  supported_model_kwargs: {
    temperature: { supported: true },
    top_p: { supported: true },
    reasoning_effort: { supported: true, control: "select", options: ["low", "medium", "high"] },
    verbosity: { supported: false },
    presence_penalty: { supported: false },
    frequency_penalty: { supported: false },
    top_k: { supported: false }
  }
} as never;

describe("behaviourFromKwargs", () => {
  it("maps the preset temperatures to their behaviours", () => {
    expect(behaviourFromKwargs({ temperature: 1.25 })).toBe("creative");
    expect(behaviourFromKwargs({ temperature: 0.25 })).toBe("deterministic");
    expect(behaviourFromKwargs({ temperature: null })).toBe("default");
    expect(behaviourFromKwargs({})).toBe("default");
  });

  it("treats anything else as custom", () => {
    expect(behaviourFromKwargs({ temperature: 0.7 })).toBe("custom");
    expect(behaviourFromKwargs(null)).toBe("custom");
  });
});

describe("kwargsForBehaviour", () => {
  it("returns the preset temperature, and null for custom", () => {
    expect(kwargsForBehaviour("creative")).toEqual({ temperature: 1.25 });
    expect(kwargsForBehaviour("default")).toEqual({ temperature: null });
    expect(kwargsForBehaviour("custom")).toBeNull();
  });
});

describe("capabilities", () => {
  it("lists only supported model-specific kwargs", () => {
    expect(modelSpecificKwargs(model)).toEqual(["reasoning_effort", "top_p"]);
    expect(modelSpecificKwargs(null)).toEqual([]);
  });

  it("requires temperature support for behaviour presets", () => {
    expect(supportsBehaviorPresets(model)).toBe(true);
    expect(supportsBehaviorPresets({ supported_model_kwargs: null })).toBe(false);
  });

  it("filters unsupported kwargs before save", () => {
    const filtered = filterSupportedKwargs(
      { temperature: 1, top_k: 5, reasoning_effort: "high" },
      model
    );
    expect(filtered).toEqual({ temperature: 1, reasoning_effort: "high" });
  });
});

/** A model whose temperature an administrator capped at 1; it takes top_p and top_k. */
const ranged = {
  supported_model_kwargs: {
    temperature: { supported: true, minimum: 0, maximum: 1 },
    top_p: { supported: true, minimum: 0, maximum: 1 },
    top_k: { supported: true, minimum: 1, maximum: 100 },
    presence_penalty: { supported: false }
  }
} as never;

describe("number settings", () => {
  it("take a value inside the model's range, and a whole number for top_k", () => {
    expect(isValidNumericKwarg(ranged, "top_p", 0)).toBe(true);
    expect(isValidNumericKwarg(ranged, "top_p", 1)).toBe(true);
    expect(isValidNumericKwarg(ranged, "top_p", -0.1)).toBe(false);
    expect(isValidNumericKwarg(ranged, "top_p", 1.1)).toBe(false);
    expect(isValidNumericKwarg(ranged, "top_p", Number.NaN)).toBe(false);
    expect(isValidNumericKwarg(ranged, "top_p", null)).toBe(true);
    expect(isValidNumericKwarg(ranged, "top_k", 40)).toBe(true);
    // The backend stores top_k as an int.
    expect(isValidNumericKwarg(ranged, "top_k", 2.5)).toBe(false);
  });

  it("fall back to the editor's ranges when the model gives none", () => {
    expect(numericKwargRange(null, "temperature")).toEqual({
      min: 0,
      max: 2,
      step: 0.05,
      wholeNumber: false
    });
    expect(numericKwargRange(null, "top_k")).toEqual({
      min: 0,
      max: 100,
      step: 1,
      wholeNumber: true
    });
  });

  it("finds the first value the model takes that cannot be saved, ignoring what it does not take", () => {
    // presence_penalty is dropped on save, so its value is not checked.
    expect(firstInvalidNumericKwarg(ranged, { presence_penalty: 99, top_p: 0.5 })).toBeNull();
    expect(firstInvalidNumericKwarg(ranged, { top_p: -0.1, top_k: 2.5 })).toBe("top_p");
    expect(firstInvalidNumericKwarg(ranged, { top_k: 2.5 })).toBe("top_k");
    // A preset's temperature is checked too: Kreativ is 1.25.
    expect(firstInvalidNumericKwarg(ranged, { temperature: 1.25 })).toBe("temperature");
  });

  it("are focused at the field that holds them", () => {
    expect(modelKwargFieldId("t", "temperature", { temperature: 0.7 })).toBe(
      "t-custom-temperature"
    );
    expect(modelKwargFieldId("t", "temperature", { temperature: 1.25 })).toBe("t-model-behaviour");
    expect(modelKwargFieldId("t", "top_k", { temperature: 0.7 })).toBe("t-kwarg-top_k");
  });
});
