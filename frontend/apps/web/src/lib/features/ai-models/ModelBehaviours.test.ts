import { expect, test } from "vitest";
import { getBehaviour, getKwargs } from "./ModelBehaviours";

test("behavior presets are determined by temperature", () => {
  expect(getBehaviour({ temperature: 1.25, top_p: 0.8 })).toBe("creative");
  expect(getBehaviour({ temperature: null, top_p: 0.8 })).toBe("default");
  expect(getBehaviour({ temperature: 0.25, top_p: null })).toBe("deterministic");
  expect(getBehaviour({ temperature: 0.7, top_p: null })).toBe("custom");
});

test("behavior presets do not overwrite model-specific top_p", () => {
  expect(getKwargs("creative")).toEqual({ temperature: 1.25 });
  expect(getKwargs("default")).toEqual({ temperature: null });
});
