import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import type { ModelProviderCapabilities } from "../../modelProviderCapabilities";
import { providerSupportsMode, staticCatalog } from "./loadModels";

const capabilities = {
  providers: {
    openai: {
      modes: ["completion", "embedding", "image"],
      models: {
        completion: [{ name: "gpt-5" }],
        image: [{ name: "gpt-image-1", cost_per_image: null }]
      },
      fields: []
    },
    hosted_vllm: {
      modes: ["completion", "embedding", "transcription", "image"],
      models: {},
      fields: []
    }
  },
  default_fields: []
} as unknown as ModelProviderCapabilities;

describe("image mode discovery", () => {
  it("reads image support from the provider's modes", () => {
    expect(providerSupportsMode(capabilities, "openai", "image")).toBe("supported");
    expect(providerSupportsMode(capabilities, "hosted_vllm", "image")).toBe("supported");
    expect(providerSupportsMode(capabilities, "openai", "transcription")).toBe("unsupported");
  });

  it("lists the static image catalog for the provider", () => {
    expect(staticCatalog(capabilities, "openai", "image")).toEqual([
      { name: "gpt-image-1", cost_per_image: null }
    ]);
    expect(staticCatalog(capabilities, "hosted_vllm", "image")).toEqual([]);
  });
});
