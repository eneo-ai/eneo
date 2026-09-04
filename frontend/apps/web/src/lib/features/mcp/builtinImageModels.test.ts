import { describe, expect, it } from "vitest";

import {
  BUILTIN_IMAGE_QUALITIES,
  BUILTIN_IMAGE_SIZES,
  hasBuiltinProvider,
  suggestedImageModels
} from "./builtinImageModels";

describe("builtin image models", () => {
  it("offers a built-in provider for image generation only", () => {
    expect(hasBuiltinProvider("image_generation")).toBe(true);
    expect(hasBuiltinProvider("web_search")).toBe(false);
    expect(hasBuiltinProvider("general")).toBe(false);
    expect(hasBuiltinProvider(null)).toBe(false);
  });

  it("suggests models per provider type, case-insensitively", () => {
    expect(suggestedImageModels("OpenAI")).toContain("gpt-image-1");
    expect(suggestedImageModels("gemini").length).toBeGreaterThan(0);
  });

  it("suggests nothing for tenant-named deployments or unknown types", () => {
    expect(suggestedImageModels("azure")).toEqual([]);
    expect(suggestedImageModels("mistral")).toEqual([]);
    expect(suggestedImageModels(undefined)).toEqual([]);
  });

  it("starts both option lists with auto", () => {
    expect(BUILTIN_IMAGE_SIZES[0]).toBe("auto");
    expect(BUILTIN_IMAGE_QUALITIES[0]).toBe("auto");
  });
});
