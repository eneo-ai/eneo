import { describe, expect, it } from "vitest";
import { hasOwnEndpoint } from "./model-catalog";

describe("hasOwnEndpoint", () => {
  // The hosts of OpenAI's own service, as the backend's live text rule lists
  // them (backend/tests/unittests/transcription_models/test_realtime_eligibility.py).
  it.each([
    "https://api.openai.com",
    "https://api.openai.com/v1",
    "https://api.openai.com/v1/",
    "HTTPS://API.OPENAI.COM:443/v1",
    "https://api.openai.com./v1",
    "https://api.openai.com。",
    "https://api.openai.com。/v1",
    "https://api.openai.com．",
    "https://api.openai.com．/v1",
    "https://api.openai.com｡",
    "https://api.openai.com｡/v1",
    "https://eu.api.openai.com/v1",
    "https://openai.com",
    " https://api.openai.com/v1 "
  ])("counts OpenAI's own host %s as no address of its own", (endpoint) => {
    expect(hasOwnEndpoint("openai", endpoint)).toBe(false);
  });

  it.each(["https://api.anthropic.com", "https://api.anthropic.com/v1/"])(
    "counts Anthropic's own host %s as no address of its own",
    (endpoint) => {
      expect(hasOwnEndpoint("anthropic", endpoint)).toBe(false);
    }
  );

  it.each([
    ["openai", "https://gateway.example.se/v1"],
    ["openai", "http://gateway.internal:8080"],
    // Only the host decides: a name that starts like OpenAI's is someone else's.
    ["openai", "https://openai.com.example.se/v1"],
    ["openai", "https://notopenai.com/v1"],
    // An address that cannot be read is not OpenAI's service either.
    ["openai", "gateway.example.se"]
  ])("counts %s at %s as an address of its own", (type, endpoint) => {
    expect(hasOwnEndpoint(type, endpoint)).toBe(true);
  });

  it.each([
    ["mistral", "https://api.mistral.ai"],
    ["mistral", "https://gateway.example.se/v1"],
    ["ollama", "http://ollama.kommun.se:11434"],
    ["anthropic", "https://proxy.kommun.se/v1"]
  ])("counts %s at %s as the type's own service, as before", (type, endpoint) => {
    expect(hasOwnEndpoint(type, endpoint)).toBe(false);
  });

  it("keeps vLLM and Azure as they were", () => {
    expect(hasOwnEndpoint("hosted_vllm", undefined)).toBe(true);
    expect(hasOwnEndpoint("azure", "https://kommun.openai.azure.com")).toBe(false);
    expect(hasOwnEndpoint("openai", "")).toBe(false);
  });
});
