import { describe, expect, it, vi } from "vitest";
import { emptySkillBindingCatalogPage } from "$lib/features/skills/skillBindingCatalog";
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
      skills: emptySkillBindingCatalogPage(),
      skillRuntimePolicy: { selective_activation_enabled: true }
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
      attachable_revision_id: "revision-1",
      slug: "first",
      revision_number: 1,
      attachable_revision_number: 1,
      display_name: "First",
      description: "First description",
      content_digest: "digest-1",
      position: 0,
      is_active: true,
      execution_blocked: false,
      activation_mode: "always" as const,
      source: "organization" as const
    };
    const second = {
      skill_id: "skill-2",
      skill_revision_id: "revision-2",
      attachable_revision_id: "revision-2",
      slug: "second",
      revision_number: 2,
      attachable_revision_number: 2,
      display_name: "Second",
      description: "Second description",
      content_digest: "digest-2",
      position: 1,
      is_active: true,
      execution_blocked: false,
      activation_mode: "always" as const,
      source: "organization" as const
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
      skills: emptySkillBindingCatalogPage(),
      skillRuntimePolicy: { selective_activation_enabled: true }
    });

    draft.skillBindings = [
      {
        skill_id: second.skill_id,
        skill_revision_id: second.skill_revision_id,
        activation_mode: "on_demand"
      },
      {
        skill_id: first.skill_id,
        skill_revision_id: first.skill_revision_id,
        activation_mode: "always"
      }
    ];
    draft.save();

    expect(draft.pendingConfirm).not.toBeNull();
    await draft.pendingConfirm?.submit();
    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(update).toHaveBeenCalledWith({
      skills: {
        bindings: [
          {
            skill_id: "skill-2",
            skill_revision_id: "revision-2",
            activation_mode: "on_demand"
          },
          {
            skill_id: "skill-1",
            skill_revision_id: "revision-1",
            activation_mode: "always"
          }
        ]
      }
    });
  });

  it("treats an activation-mode-only change as a saveable Skill change", async () => {
    const update = vi.fn(async () => {});
    const binding = {
      skill_id: "skill-1",
      skill_revision_id: "revision-1",
      attachable_revision_id: "revision-1",
      slug: "analysis",
      revision_number: 1,
      attachable_revision_number: 1,
      display_name: "Analysis",
      description: "Analysis guidance",
      content_digest: "digest-1",
      position: 0,
      is_active: true,
      execution_blocked: false,
      activation_mode: "always" as const,
      source: "organization" as const
    };
    const draft = new PolicyDraft();
    draft.sync({
      eneo: { governancePolicy: { update } } as never,
      policy: {
        models_restriction: {
          enabled: true,
          models: [{ completion_model_id: "model-1", is_default: true }],
          provider_ids: []
        },
        mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
        prompt_enforcement: { enabled: false, prompt_library_id: null },
        skills: { bindings: [binding] }
      },
      models: {
        completionModels: [
          {
            id: "model-1",
            name: "Model",
            can_access: true,
            supports_tool_calling: true
          }
        ]
      },
      modelProviders: [],
      mcpSettings: { items: [] },
      promptLibrary: { items: [] },
      skills: emptySkillBindingCatalogPage(),
      skillRuntimePolicy: { selective_activation_enabled: true }
    });

    draft.skillBindings = [{ ...draft.skillBindings[0], activation_mode: "on_demand" }];

    expect(draft.dirty).toBe(true);
    draft.toggleProvider("provider-1", true);
    expect(draft.canSelectOnDemand).toBe(false);
    expect(draft.canSave).toBe(false);

    draft.toggleProvider("provider-1", false);
    expect(draft.canSelectOnDemand).toBe(true);
    expect(draft.canSave).toBe(true);
    draft.save();
    await draft.pendingConfirm?.submit();
    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(update).toHaveBeenCalledWith({
      skills: {
        bindings: [
          {
            skill_id: "skill-1",
            skill_revision_id: "revision-1",
            activation_mode: "on_demand"
          }
        ]
      }
    });
  });

  it("keeps On demand unavailable while the tenant disables selective activation", () => {
    const binding = {
      skill_id: "skill-1",
      skill_revision_id: "revision-1",
      attachable_revision_id: "revision-1",
      slug: "analysis",
      revision_number: 1,
      attachable_revision_number: 1,
      display_name: "Analysis",
      description: "Analysis guidance",
      content_digest: "digest-1",
      position: 0,
      is_active: true,
      execution_blocked: false,
      activation_mode: "always" as const,
      source: "organization" as const
    };
    // A bounded, tool-capable model selection — the only prerequisite the page
    // used to check before the tenant runtime switch was consulted.
    const pageData = (selectiveActivationEnabled: boolean) => ({
      eneo: { governancePolicy: { update: vi.fn(async () => {}) } } as never,
      policy: {
        models_restriction: {
          enabled: true,
          models: [{ completion_model_id: "model-1", is_default: true }],
          provider_ids: []
        },
        mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
        prompt_enforcement: { enabled: false, prompt_library_id: null },
        skills: { bindings: [binding] }
      },
      models: {
        completionModels: [
          { id: "model-1", name: "Model", can_access: true, supports_tool_calling: true }
        ]
      },
      modelProviders: [],
      mcpSettings: { items: [] },
      promptLibrary: { items: [] },
      skills: emptySkillBindingCatalogPage(),
      skillRuntimePolicy: { selective_activation_enabled: selectiveActivationEnabled }
    });

    const draft = new PolicyDraft();
    draft.sync(pageData(false));
    draft.skillBindings = [{ ...draft.skillBindings[0], activation_mode: "on_demand" }];

    expect(draft.canSelectOnDemand).toBe(false);
    expect(draft.dirty).toBe(true);
    expect(draft.skillsValid).toBe(false);
    expect(draft.canSave).toBe(false);

    draft.sync(pageData(true));
    draft.skillBindings = [{ ...draft.skillBindings[0], activation_mode: "on_demand" }];

    expect(draft.canSelectOnDemand).toBe(true);
    expect(draft.skillsValid).toBe(true);
    expect(draft.canSave).toBe(true);
  });

  it("seeds the bounded Skill catalogue supplied by the page loader", () => {
    const approved = {
      id: "skill-1",
      slug: "leave",
      revision_id: "revision-2",
      revision_number: 2,
      display_name: "Leave",
      description: "Approved leave guidance",
      content_digest: "digest-2",
      first_published_at: "2026-07-20T12:00:00Z",
      execution_blocked: false,
      source: "organization" as const
    };
    const skills = {
      items: [approved],
      count: 1,
      limit: 25,
      next_cursor: null
    };
    const draft = new PolicyDraft();
    draft.sync({
      eneo: { governancePolicy: { update: vi.fn(async () => {}) } } as never,
      policy: {
        models_restriction: { enabled: false, models: [], provider_ids: [] },
        mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
        prompt_enforcement: { enabled: false, prompt_library_id: null },
        skills: { bindings: [] }
      },
      models: { completionModels: [] },
      modelProviders: [],
      mcpSettings: { items: [] },
      promptLibrary: { items: [] },
      skills,
      skillRuntimePolicy: { selective_activation_enabled: true }
    });

    expect(draft.skillCatalogPage).toEqual(skills);
  });
});
