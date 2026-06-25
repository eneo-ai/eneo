import { describe, expect, it } from "vitest";
import { selectEffectiveChatModel } from "./selectEffectiveChatModel";

describe("selectEffectiveChatModel", () => {
  it("uses backend order instead of display sorting when no default exists", () => {
    const backendFirst = { id: "created-first", label: "Zulu" };
    const alphabeticFirst = { id: "created-second", label: "Alpha" };

    const selected = selectEffectiveChatModel(
      { id: "stale", label: "Stale" },
      {
        models_enforced: true,
        available_models: [backendFirst, alphabeticFirst]
      },
      [alphabeticFirst, backendFirst]
    );

    expect(selected).toBe(backendFirst);
  });

  it("returns the catalog object for the backend-selected model", () => {
    const sparse = { id: "model" };
    const full = { id: "model", label: "Full model" };

    expect(
      selectEffectiveChatModel(
        undefined,
        {
          models_enforced: true,
          default_model: sparse,
          available_models: [sparse]
        },
        [full]
      )
    ).toBe(full);
  });
});
