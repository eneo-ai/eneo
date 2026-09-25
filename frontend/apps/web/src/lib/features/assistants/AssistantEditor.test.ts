import { get } from "svelte/store";
import { describe, expect, test, vi } from "vitest";
import type { Assistant, Eneo } from "@eneo/eneo-js";

vi.mock("$lib/core/context", () => ({
  createContext: () => [() => undefined, () => undefined]
}));
vi.mock("$lib/core/errors", () => ({ toastError: () => undefined }));

import { initAssistantEditor } from "./AssistantEditor";

describe("AssistantEditor knowledge mode", () => {
  test("a missing setting defaults to legacy injected retrieval", () => {
    const assistant = { id: "assistant-1", name: "Legacy" } as unknown as Assistant;
    const eneo = {
      assistants: { update: vi.fn() }
    } as unknown as Eneo;

    const editor = initAssistantEditor({ assistant, eneo });

    expect(get(editor.state.update).knowledge_mode).toBe("inject");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(false);
  });
});
