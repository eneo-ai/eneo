import { describe, expect, it } from "vitest";
import { findTemplateModel } from "./templates";

const MODELS = [
  { id: "m1", name: "gpt-4o" },
  { id: "m2", name: "gpt-4o" },
  { id: "m3", name: "claude-sonnet" }
];

describe("findTemplateModel", () => {
  it("keeps the template's own model even when an earlier one has its name", () => {
    expect(
      findTemplateModel(MODELS, { completion_model_id: "m2", completion_model_name: "gpt-4o" })?.id
    ).toBe("m2");
  });

  it("falls back to the name, then to the first model", () => {
    expect(
      findTemplateModel(MODELS, {
        completion_model_id: "gone",
        completion_model_name: "claude-sonnet"
      })?.id
    ).toBe("m3");
    expect(findTemplateModel(MODELS, { completion_model_id: null })?.id).toBe("m1");
    expect(findTemplateModel(MODELS)?.id).toBe("m1");
    expect(findTemplateModel([], { completion_model_id: "m1" })).toBeNull();
  });
});
