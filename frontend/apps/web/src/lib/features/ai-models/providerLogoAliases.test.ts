import { expect, test } from "vitest";

import { resolveProviderLogoType } from "./providerLogoAliases";

test("provider logo aliases are display-only logo type mappings", () => {
  expect(resolveProviderLogoType("azure_ai")).toBe("azure");
  expect(resolveProviderLogoType("cohere_chat")).toBe("cohere");
  expect(resolveProviderLogoType("fireworks_ai-embedding-models")).toBe("fireworks_ai");
  expect(resolveProviderLogoType("text-completion-openai")).toBe("openai");
});

test("provider logo aliases normalize vendor labels used by model selectors", () => {
  expect(resolveProviderLogoType("Google")).toBe("gemini");
  expect(resolveProviderLogoType("Meta")).toBe("meta_llama");
  expect(resolveProviderLogoType("Microsoft")).toBe("azure");
  expect(resolveProviderLogoType("  Anthropic  ")).toBe("anthropic");
});

test("provider logo aliases collapse LiteLLM vertex provider variants", () => {
  expect(resolveProviderLogoType("vertex_ai")).toBe("vertex_ai");
  expect(resolveProviderLogoType("vertex_ai-anthropic_models")).toBe("vertex_ai");
});

test("provider logo aliases leave unknown provider types unchanged", () => {
  expect(resolveProviderLogoType("custom_provider")).toBe("custom_provider");
  expect(resolveProviderLogoType("")).toBeUndefined();
  expect(resolveProviderLogoType(null)).toBeUndefined();
});
