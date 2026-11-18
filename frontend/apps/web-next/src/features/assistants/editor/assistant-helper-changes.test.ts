import { describe, expect, it } from "vitest";
import {
  changeState,
  proposalUsed,
  settingInRequest,
  type AssistantChange
} from "./assistant-helper-changes";
import type { Assistant } from "./use-assistant";

const assistant = (overrides: Record<string, unknown> = {}) =>
  ({
    id: "assistant-1",
    name: "Skolhjälpen",
    description: null,
    prompt: { text: "Svara kort." },
    completion_model: { id: "model-1", name: "claude-haiku" },
    completion_model_kwargs: { temperature: 0.2 },
    knowledge_mode: "tool",
    inline_file_text: false,
    ...overrides
  }) as unknown as Assistant;

describe("Where a change the helper made stands", () => {
  const temperature: AssistantChange = {
    changes: [
      { field: "completion_model_kwargs.temperature", before: 0.7, after: 0.2, tooLong: false }
    ],
    undo: { completion_model_kwargs: { temperature: 0.7 } }
  };

  it("can be undone while the setting has the change's value, and is undone once it is back", () => {
    expect(changeState(temperature, assistant())).toBe("current");
    expect(
      changeState(temperature, assistant({ completion_model_kwargs: { temperature: 0.7 } }))
    ).toBe("undone");
    expect(
      changeState(temperature, assistant({ completion_model_kwargs: { temperature: 0.5 } }))
    ).toBe("changed");
  });

  it("counts a model given to an assistant that had none as undone with the rest", () => {
    const change: AssistantChange = {
      changes: [
        { field: "name", before: "Hjälpen", after: "Skolhjälpen", tooLong: false },
        {
          field: "completion_model",
          before: null,
          after: { id: "model-1", name: "claude-haiku" },
          tooLong: false
        }
      ],
      // An update cannot take a model away: the undo leaves it.
      undo: { name: "Hjälpen" }
    };

    expect(changeState(change, assistant())).toBe("current");
    expect(changeState(change, assistant({ name: "Hjälpen" }))).toBe("undone");
  });

  it("cannot be undone without an undo request", () => {
    expect(changeState({ ...temperature, undo: null }, assistant())).toBe("permanent");
  });
});

describe("A proposal in use", () => {
  it("reads a cleared description as no text", () => {
    expect(
      proposalUsed(
        {
          changes: [{ field: "description", before: "Gammal", after: null, tooLong: false }],
          update: { description: null }
        },
        assistant({ description: "" })
      )
    ).toBe(true);
  });

  it("reads model settings left out of a request as the model's default", () => {
    const update = { completion_model_kwargs: { temperature: 0.2 } };
    expect(settingInRequest(update, "completion_model_kwargs.top_p")).toBeNull();
    expect(settingInRequest(update, "completion_model_kwargs.temperature")).toBe(0.2);
    expect(settingInRequest(update, "name")).toBeUndefined();
  });
});
