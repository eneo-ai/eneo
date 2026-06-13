import { describe, expect, it } from "vitest";
import { selectEffectiveModelId } from "./select-effective-chat-model";

describe("selectEffectiveModelId", () => {
  it("returns the current pick unchanged when models are not enforced", () => {
    expect(selectEffectiveModelId("a", { models_enforced: false, available_models: [] })).toBe("a");
    expect(selectEffectiveModelId(null, null)).toBeUndefined();
  });

  it("keeps the current pick when it is in the enforced allow-list", () => {
    expect(
      selectEffectiveModelId("b", {
        models_enforced: true,
        available_models: [{ id: "a" }, { id: "b" }]
      })
    ).toBe("b");
  });

  it("falls back to default → locked → first allowed when the pick is disallowed", () => {
    expect(
      selectEffectiveModelId("x", {
        models_enforced: true,
        default_model: { id: "d" },
        locked_model: { id: "l" },
        available_models: [{ id: "a" }]
      })
    ).toBe("d");
    expect(
      selectEffectiveModelId("x", {
        models_enforced: true,
        locked_model: { id: "l" },
        available_models: [{ id: "a" }]
      })
    ).toBe("l");
    expect(
      selectEffectiveModelId("x", { models_enforced: true, available_models: [{ id: "a" }] })
    ).toBe("a");
  });

  it("returns undefined when enforced with no allowed models", () => {
    expect(
      selectEffectiveModelId("x", { models_enforced: true, available_models: [] })
    ).toBeUndefined();
  });
});
