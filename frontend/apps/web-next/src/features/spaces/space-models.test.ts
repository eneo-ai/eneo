import { describe, expect, it } from "vitest";
import { makeAssistant, makeSpace } from "./testing/space-fixture";
import { assistantModelName } from "./space-models";

describe("assistantModelName", () => {
  it("names the model the space offers, and nothing for a group chat or a model it no longer has", () => {
    const space = makeSpace();
    expect(assistantModelName(space, makeAssistant() as never)).toBe("Haiku 4.5");
    expect(
      assistantModelName(space, makeAssistant({ completion_model_id: "model-2" }) as never)
    ).toBe("claude-opus");
    expect(
      assistantModelName(space, makeAssistant({ completion_model_id: "gone" }) as never)
    ).toBeNull();
    expect(
      assistantModelName(space, { ...(makeAssistant() as object), type: "group-chat" } as never)
    ).toBeNull();
  });
});
