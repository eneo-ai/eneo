import { describe, expect, it, vi } from "vitest";
import { PolicyDraft } from "./policyDraft.svelte";

vi.mock("$app/navigation", () => ({
  invalidate: vi.fn(async () => {})
}));

describe("PolicyDraft", () => {
  it("does not submit hidden MCP grants when only the prompt changes", async () => {
    const update = vi.fn(async () => {});
    const draft = new PolicyDraft();
    draft.sync({
      eneo: { governancePolicy: { update } } as never,
      policy: {
        models_restriction: { enabled: false, models: [], provider_ids: [] },
        mcp_restriction: {
          enabled: true,
          servers: [{ mcp_server_id: "disabled-server", is_default_enabled: true }],
          disabled_tool_ids: ["disabled-tool"]
        },
        prompt_enforcement: { enabled: true, prompt_library_id: "prompt-1" }
      },
      models: { completionModels: [] },
      modelProviders: [],
      mcpSettings: { items: [] },
      promptLibrary: {
        items: [
          { id: "prompt-1", name: "One" },
          { id: "prompt-2", name: "Two" }
        ]
      }
    });

    draft.selectedPromptId = "prompt-2";
    draft.save();

    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(update).toHaveBeenCalledWith({
      prompt_enforcement: {
        enabled: true,
        prompt_library_id: "prompt-2"
      }
    });
  });
});
