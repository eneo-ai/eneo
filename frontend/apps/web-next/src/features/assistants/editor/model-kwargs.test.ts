import { describe, expect, it } from "vitest";
import {
  behaviourFromKwargs,
  filterSupportedKwargs,
  kwargsForBehaviour,
  modelSpecificKwargs,
  supportsBehaviorPresets
} from "./model-kwargs";

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
