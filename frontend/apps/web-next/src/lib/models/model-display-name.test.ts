import { describe, expect, it } from "vitest";
import { humaniseModelId, modelDisplayName, modelTechnicalId } from "./model-display-name";

describe("modelDisplayName (display name equal to the id)", () => {
  it("humanises when the display name only repeats the id", () => {
    expect(modelDisplayName({ name: "claude-opus-4-6", display_name: "claude-opus-4-6" })).toBe(
      "Claude Opus 4.6"
    );
  });
});

describe("modelDisplayName", () => {
  it("prefers the nickname, then the catalog display name", () => {
    expect(modelDisplayName({ name: "claude-haiku-4-5", nickname: "Haiku" })).toBe("Haiku");
    expect(modelDisplayName({ name: "claude-haiku-4-5", display_name: "Claude Haiku" })).toBe(
      "Claude Haiku"
    );
    expect(
      modelDisplayName({ name: "claude-haiku-4-5", nickname: "  ", display_name: "Claude Haiku" })
    ).toBe("Claude Haiku");
  });

  it("falls back to a readable id", () => {
    expect(modelDisplayName({ name: "claude-haiku-4-5", nickname: null })).toBe("Claude Haiku 4.5");
  });
});

describe("humaniseModelId", () => {
  it.each([
    ["claude-haiku-4-5", "Claude Haiku 4.5"],
    ["claude-3-5-sonnet", "Claude 3.5 Sonnet"],
    ["claude-sonnet-4", "Claude Sonnet 4"],
    ["mistral-large", "Mistral Large"],
    ["gemini-2-5-pro", "Gemini 2.5 Pro"],
    ["gpt-5", "GPT-5"],
    ["gpt-4-1", "GPT-4.1"],
    ["gpt-4-turbo", "GPT-4 Turbo"],
    ["gpt-5-mini", "GPT-5 Mini"]
  ])("%s → %s", (id, expected) => {
    expect(humaniseModelId(id)).toBe(expected);
  });

  it.each([
    "gpt-4o",
    "gpt-4o-mini",
    "llama-3-70b",
    "text-embedding-3-small-2024",
    "gpt-4o-2024-08-06",
    "meta-llama/Meta-Llama-3-70B-Instruct",
    "azure:gpt-4",
    "Claude Haiku 4.5"
  ])("keeps %s, where a guess could mislead", (id) => {
    expect(humaniseModelId(id)).toBe(id);
  });
});

describe("modelTechnicalId", () => {
  it("is the raw id only when the name shown differs from it", () => {
    expect(modelTechnicalId({ name: "claude-haiku-4-5", nickname: "Claude Haiku 4.5" })).toBe(
      "claude-haiku-4-5"
    );
    expect(modelTechnicalId({ name: "claude-haiku-4-5" })).toBe("claude-haiku-4-5");
    expect(modelTechnicalId({ name: "gpt-4o" })).toBeNull();
    expect(modelTechnicalId({ name: "gpt-4o", nickname: "gpt-4o" })).toBeNull();
  });
});
