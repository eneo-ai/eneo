import { EneoError, type AssistantSkillBindingSummary } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import {
  fromSavedBindings,
  loadPersonalChatSkillConfiguration,
  personalSkillBindings,
  personalSkillHasNewerRevision,
  personalSkillLayerMessage,
  personalSkillRows,
  personalSkillsSaveErrorMessage,
  runningPersonalChatSkills,
  withLatestPersonalSkillRevision,
  withPersonalSkillMode
} from "./personalChatSkills";

function binding(
  id: string,
  overrides: Partial<AssistantSkillBindingSummary> = {}
): AssistantSkillBindingSummary {
  return {
    skill_id: id,
    skill_revision_id: `${id}-r1`,
    attachable_revision_id: `${id}-r1`,
    slug: id,
    revision_number: 1,
    attachable_revision_number: 1,
    display_name: `Skill ${id}`,
    description: `Description ${id}`,
    content_digest: "digest",
    position: 0,
    is_active: true,
    source: "space",
    execution_blocked: false,
    activation_mode: "always",
    ...overrides
  };
}

function rejection(reason: string, detail: string | null = null) {
  return new EneoError("Refused", "RESPONSE", 400, 9080, {
    eneo_error_code: 9080,
    details: { reason, detail }
  });
}

describe("personal chat Skill bindings", () => {
  test("sends the saved bindings in their position order with their exact revision and mode", () => {
    expect(
      personalSkillBindings([
        binding("b", { position: 1, activation_mode: "on_demand" }),
        binding("a", { position: 0 })
      ])
    ).toEqual([
      { skill_id: "a", skill_revision_id: "a-r1", activation_mode: "always" },
      { skill_id: "b", skill_revision_id: "b-r1", activation_mode: "on_demand" }
    ]);
  });

  test("turns a Skill on at its current revision, changes a mode in place and leaves it out when off", () => {
    const saved = personalSkillBindings([binding("a"), binding("b", { position: 1 })]);

    expect(withPersonalSkillMode(saved, { id: "c", revisionId: "c-r4" }, "on_demand")).toEqual([
      ...saved,
      { skill_id: "c", skill_revision_id: "c-r4", activation_mode: "on_demand" }
    ]);
    // An existing binding keeps its pinned revision even when a newer one exists.
    expect(withPersonalSkillMode(saved, { id: "a", revisionId: "a-r9" }, "on_demand")).toEqual([
      { skill_id: "a", skill_revision_id: "a-r1", activation_mode: "on_demand" },
      saved[1]
    ]);
    expect(withPersonalSkillMode(saved, { id: "a", revisionId: "a-r1" }, "off")).toEqual([
      saved[1]
    ]);
  });

  test("offers no newer revision for a deactivated Skill, which cannot move", () => {
    const newer = { attachable_revision_id: "a-r2", attachable_revision_number: 2 };
    expect(personalSkillHasNewerRevision(binding("a", newer))).toBe(true);
    expect(personalSkillHasNewerRevision(binding("a", { ...newer, is_active: false }))).toBe(false);
  });

  test("moves one Skill to the revision the person reviewed and keeps the rest as saved", () => {
    const newer = binding("a", { attachable_revision_id: "a-r2", attachable_revision_number: 2 });
    const saved = personalSkillBindings([newer, binding("b", { position: 1 })]);

    expect(personalSkillHasNewerRevision(newer)).toBe(true);
    expect(personalSkillHasNewerRevision(binding("b"))).toBe(false);
    expect(withLatestPersonalSkillRevision(saved, newer)).toEqual([
      { skill_id: "a", skill_revision_id: "a-r2", activation_mode: "always" },
      saved[1]
    ]);
  });
});

describe("the person's own Skill rows", () => {
  test("lists the library with each Skill's chosen mode, leaving out unavailable Skills not in the chat", () => {
    const saved = [binding("a", { attachable_revision_id: "a-r2" })];
    const library = [
      { id: "a", display_name: "A", description: "", is_active: true, current_revision_id: "a-r2" },
      { id: "b", display_name: "B", description: "", is_active: true, current_revision_id: "b-r3" },
      { id: "c", display_name: "C", description: "", is_active: false, current_revision_id: "c-r1" }
    ];

    const rows = personalSkillRows(saved, library as never, personalSkillBindings(saved));

    expect(
      rows.map(({ id, mode, revisionId, hasNewerRevision }) => ({
        id,
        mode,
        revisionId,
        hasNewerRevision
      }))
    ).toEqual([
      { id: "a", mode: "always", revisionId: "a-r2", hasNewerRevision: true },
      { id: "b", mode: "off", revisionId: "b-r3", hasNewerRevision: false }
    ]);
    expect(rows[0].binding).toBe(saved[0]);
  });

  test("re-adds a Skill no loaded page shows at its newest revision, and keeps its pin on a mode change", () => {
    const saved = [binding("a", { attachable_revision_id: "a-r2", attachable_revision_number: 2 })];
    const [row] = personalSkillRows(saved, [], personalSkillBindings(saved));

    expect(withPersonalSkillMode(personalSkillBindings(saved), row, "on_demand")).toEqual([
      { skill_id: "a", skill_revision_id: "a-r1", activation_mode: "on_demand" }
    ]);
    const off = withPersonalSkillMode(personalSkillBindings(saved), row, "off");
    expect(off).toEqual([]);
    expect(withPersonalSkillMode(off, row, "always")).toEqual([
      { skill_id: "a", skill_revision_id: "a-r2", activation_mode: "always" }
    ]);
  });

  test("follows the change being saved and keeps Skills in the chat that no loaded page shows", () => {
    const saved = [binding("a", { attachable_revision_id: "a-r2" }), binding("z", { position: 1 })];
    const moved = [
      { skill_id: "a", skill_revision_id: "a-r2", activation_mode: "on_demand" as const },
      { skill_id: "z", skill_revision_id: "z-r1", activation_mode: "always" as const }
    ];
    const library = [
      { id: "b", display_name: "B", description: "", is_active: true, current_revision_id: "b-r1" }
    ];

    expect(personalSkillRows(saved, library as never, moved)).toMatchObject([
      { id: "b", mode: "off" },
      { id: "a", name: "Skill a", mode: "on_demand", hasNewerRevision: false },
      { id: "z", mode: "always" }
    ]);
    // A search shows what the server found, and only that.
    expect(
      personalSkillRows(saved, library as never, moved, { searching: true }).map((row) => row.id)
    ).toEqual(["b"]);
  });
});

describe("saving a personal chat Skill change", () => {
  test("applies the change to what is saved when its turn comes, not when it was made", async () => {
    let saved = [binding("a"), binding("b", { position: 1 })];
    const build = fromSavedBindings(
      async () => ({ bindings: saved, runtime: null }),
      (bindings) => withPersonalSkillMode(bindings, { id: "c", revisionId: "c-r1" }, "always")
    );
    // An earlier save in the queue switched b off.
    saved = [binding("a")];

    await expect(build()).resolves.toEqual([
      { skill_id: "a", skill_revision_id: "a-r1", activation_mode: "always" },
      { skill_id: "c", skill_revision_id: "c-r1", activation_mode: "always" }
    ]);
  });
});

describe("Skills that run in the personal chat", () => {
  test("counts the organisation's unblocked Skills and the person's own unless they are paused", () => {
    const organisation_bindings = [
      binding("org-1"),
      binding("org-2", { activation_mode: "on_demand" }),
      binding("org-3", { execution_blocked: true })
    ];
    const bindings = [
      binding("own-1", { activation_mode: "on_demand" }),
      binding("own-2", { execution_blocked: true })
    ];

    expect(
      runningPersonalChatSkills({
        bindings,
        organisation_bindings,
        runtime: null,
        personal_layer: { status: "applied", reason: null, detail: null }
      })
    ).toEqual({ always: 1, on_demand: 2 });
    expect(
      runningPersonalChatSkills({
        bindings,
        organisation_bindings,
        runtime: null,
        personal_layer: { status: "suspended", reason: "model_context_exceeded", detail: null }
      })
    ).toEqual({ always: 1, on_demand: 1 });
    // Without a model there is no assessment, and nothing says they are paused.
    expect(runningPersonalChatSkills({ bindings, organisation_bindings, runtime: null })).toEqual({
      always: 1,
      on_demand: 2
    });
  });
});

describe("personal chat Skill messages", () => {
  test("explains a paused layer by its reason and names a switched-off on-demand mode", () => {
    expect(personalSkillLayerMessage({ reason: "model_context_exceeded", detail: null })).toBe(
      m.personal_chat_skills_reason_model_context_exceeded()
    );
    expect(
      personalSkillLayerMessage({
        reason: "on_demand_unavailable",
        detail: "model_lacks_tool_calling"
      })
    ).toBe(m.personal_chat_skills_reason_on_demand_unavailable());
    expect(
      personalSkillLayerMessage({
        reason: "on_demand_unavailable",
        detail: "selective_activation_disabled"
      })
    ).toBe(m.personal_chat_skills_reason_on_demand_disabled());
  });

  test("explains a refused save by its reason, a 403 as a missing permission and anything else as not saved", () => {
    expect(personalSkillsSaveErrorMessage(rejection("attachment_limit_exceeded"))).toBe(
      m.personal_chat_skills_reason_attachment_limit_exceeded()
    );
    expect(
      personalSkillsSaveErrorMessage(new EneoError("Forbidden", "RESPONSE", 403, 9001, {}))
    ).toBe(m.personal_chat_skills_reason_permission_missing());
    expect(personalSkillsSaveErrorMessage(rejection("a_reason_from_a_newer_backend"))).toBe(
      m.personal_chat_skills_save_failed()
    );
    expect(personalSkillsSaveErrorMessage(new Error("offline"))).toBe(
      m.personal_chat_skills_save_failed()
    );
  });
});

describe("personal chat Skill configuration for the Skills pages", () => {
  test("reads the personal chat's configuration only in the personal space", async () => {
    const configuration = { bindings: [], runtime: null };
    const getAssistantConfiguration = vi.fn(async () => configuration);
    const eneo = { skills: { getAssistantConfiguration } } as never;

    await expect(
      loadPersonalChatSkillConfiguration(eneo, {
        id: "personal-space",
        personal: true,
        default_assistant: { id: "default-assistant" }
      })
    ).resolves.toBe(configuration);
    expect(getAssistantConfiguration).toHaveBeenCalledWith({
      spaceId: "personal-space",
      assistantId: "default-assistant"
    });

    await expect(
      loadPersonalChatSkillConfiguration(eneo, {
        id: "shared-space",
        personal: false,
        default_assistant: { id: "assistant" }
      })
    ).resolves.toBeNull();
    expect(getAssistantConfiguration).toHaveBeenCalledOnce();
  });

  test("keeps the Skills pages usable when the personal chat cannot be read", async () => {
    const eneo = {
      skills: { getAssistantConfiguration: vi.fn().mockRejectedValue(new Error("403")) }
    } as never;

    await expect(
      loadPersonalChatSkillConfiguration(eneo, {
        id: "personal-space",
        personal: true,
        default_assistant: { id: "default-assistant" }
      })
    ).resolves.toBeNull();
  });
});
