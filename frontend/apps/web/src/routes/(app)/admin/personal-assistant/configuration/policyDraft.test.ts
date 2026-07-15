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
        prompt_enforcement: { enabled: true, prompt_library_id: "prompt-1" },
        skills: { bindings: [] }
      },
      models: { completionModels: [] },
      modelProviders: [],
      mcpSettings: { items: [] },
      promptLibrary: {
        items: [
          { id: "prompt-1", name: "One" },
          { id: "prompt-2", name: "Two" }
        ]
      },
      organizationSpace: {
        id: "organization-space",
        skill_permissions: ["read", "create", "edit"]
      },
      skills: []
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

  it("submits an ordered exact Skill facet without resubmitting other dimensions", async () => {
    const update = vi.fn(async () => {});
    const first = {
      skill_id: "skill-1",
      skill_revision_id: "revision-1",
      slug: "first",
      revision_number: 1,
      display_name: "First",
      description: "First description",
      content_digest: "digest-1",
      position: 0,
      is_active: true
    };
    const second = {
      skill_id: "skill-2",
      skill_revision_id: "revision-2",
      slug: "second",
      revision_number: 2,
      display_name: "Second",
      description: "Second description",
      content_digest: "digest-2",
      position: 1,
      is_active: true
    };
    const draft = new PolicyDraft();
    draft.sync({
      eneo: { governancePolicy: { update } } as never,
      policy: {
        models_restriction: { enabled: false, models: [], provider_ids: [] },
        mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
        prompt_enforcement: { enabled: false, prompt_library_id: null },
        skills: { bindings: [first, second] }
      },
      models: { completionModels: [] },
      modelProviders: [],
      mcpSettings: { items: [] },
      promptLibrary: { items: [] },
      organizationSpace: {
        id: "organization-space",
        skill_permissions: ["read", "create", "edit"]
      },
      skills: []
    });

    draft.skillBindings = [
      { skill_id: second.skill_id, skill_revision_id: second.skill_revision_id },
      { skill_id: first.skill_id, skill_revision_id: first.skill_revision_id }
    ];
    draft.save();

    expect(draft.pendingConfirm).not.toBeNull();
    await draft.pendingConfirm?.submit();
    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(update).toHaveBeenCalledWith({
      skills: {
        bindings: [
          { skill_id: "skill-2", skill_revision_id: "revision-2" },
          { skill_id: "skill-1", skill_revision_id: "revision-1" }
        ]
      }
    });
  });
});
