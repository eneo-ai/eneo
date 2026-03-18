import { describe, expect, it, vi, afterEach } from "vitest";

import { AssistantSaveManager } from "./flowAssistantSaveManager";

type AssistantRecord = {
  id: string;
  prompt?: { text?: string; description?: string };
  completion_model?: { id: string };
};

function createManager(overrides: {
  loadRemote?: (assistantId: string) => Promise<AssistantRecord | null>;
  saveRemote?: (assistantId: string, changes: Record<string, unknown>) => Promise<AssistantRecord>;
  shouldSaveImmediately?: (changes: Record<string, unknown>) => boolean;
  isDisabled?: () => boolean;
  onPromptSaved?: () => void;
  onValidationError?: (assistantId: string, message: string | null) => void;
} = {}) {
  const loadRemote =
    overrides.loadRemote ??
    vi.fn(async (assistantId: string) => ({
      id: assistantId,
      prompt: { text: "Original" }
    }));
  const saveRemote =
    overrides.saveRemote ??
    vi.fn(async (assistantId: string, changes: Record<string, unknown>) => ({
      id: assistantId,
      ...changes
    }));
  const onPromptSaved = overrides.onPromptSaved ?? vi.fn();
  const onValidationError = overrides.onValidationError ?? vi.fn();

  const manager = new AssistantSaveManager<AssistantRecord>({
    loadRemote,
    saveRemote,
    shouldSaveImmediately: overrides.shouldSaveImmediately ?? (() => false),
    isDisabled: overrides.isDisabled ?? (() => false),
    getErrorMessage: () => "assistant_save_failed",
    onPromptSaved,
    onValidationError,
    delayMs: 500
  });

  return {
    manager,
    loadRemote,
    saveRemote,
    onPromptSaved,
    onValidationError
  };
}

describe("AssistantSaveManager", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces and merges pending assistant changes", async () => {
    const { manager, saveRemote } = createManager();

    await manager.save("assistant-1", {
      prompt: { text: "Draft one" }
    });
    await manager.save("assistant-1", {
      prompt: { text: "Draft two" }
    });

    expect(manager.getStatus()).toBe("pending");
    expect(saveRemote).not.toHaveBeenCalled();

    await new Promise((resolve) => setTimeout(resolve, 550));

    expect(saveRemote).toHaveBeenCalledTimes(1);
    expect(saveRemote).toHaveBeenCalledWith("assistant-1", {
      prompt: { text: "Draft two" }
    });
    expect(manager.getStatus()).toBe("idle");
  });

  it("overlays pending unsaved changes when loading an assistant", async () => {
    const { manager } = createManager();

    manager.primeCache("assistant-1", {
      id: "assistant-1",
      prompt: { text: "Original" }
    });
    await manager.save("assistant-1", {
      prompt: { text: "Pending" }
    });

    await expect(manager.load("assistant-1")).resolves.toEqual({
      id: "assistant-1",
      prompt: { text: "Pending" }
    });
  });

  it("saves immediately when the change policy requires it", async () => {
    const { manager, saveRemote } = createManager({
      shouldSaveImmediately: (changes) => "completion_model" in changes
    });

    await manager.save("assistant-1", {
      completion_model: { id: "model-1" }
    });

    expect(saveRemote).toHaveBeenCalledTimes(1);
    expect(saveRemote).toHaveBeenCalledWith("assistant-1", {
      completion_model: { id: "model-1" }
    });
    expect(manager.getStatus()).toBe("idle");
  });

  it("flushes queued saves and triggers prompt-save callbacks for prompt changes", async () => {
    const { manager, saveRemote, onPromptSaved } = createManager();

    await manager.save("assistant-1", {
      prompt: { text: "Queued prompt" }
    });

    await manager.flush();

    expect(saveRemote).toHaveBeenCalledTimes(1);
    expect(onPromptSaved).toHaveBeenCalledTimes(1);
    expect(manager.getStatus()).toBe("idle");
  });
});
