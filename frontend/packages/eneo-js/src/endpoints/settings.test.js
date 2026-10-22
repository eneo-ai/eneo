import { describe, expect, it, vi } from "vitest";

import { initSettings } from "./settings";

describe("settings Skill policy endpoints", () => {
  it("uses the typed routes for organisation Skill execution blocks", async () => {
    const fetch = vi.fn(async () => ({ skill_id: "skill-1", block: null }));
    const settings = initSettings({ fetch });

    await settings.getSkillExecutionBlock({ skillId: "skill-1" });
    await settings.blockSkillExecution({
      skillId: "skill-1",
      reason: "Confirmed unsafe instructions"
    });
    await settings.unblockSkillExecution({
      skillId: "skill-1",
      expectedBlockId: "block-1",
      reason: "Removed the harmful revision"
    });

    expect(fetch.mock.calls).toEqual([
      [
        "/api/v1/settings/skills/{skill_id}/execution-block",
        { method: "get", params: { path: { skill_id: "skill-1" } } }
      ],
      [
        "/api/v1/settings/skills/{skill_id}/execution-block",
        {
          method: "post",
          params: { path: { skill_id: "skill-1" } },
          requestBody: {
            "application/json": { reason: "Confirmed unsafe instructions" }
          }
        }
      ],
      [
        "/api/v1/settings/skills/{skill_id}/execution-block/unblock",
        {
          method: "post",
          params: { path: { skill_id: "skill-1" } },
          requestBody: {
            "application/json": {
              expected_block_id: "block-1",
              reason: "Removed the harmful revision"
            }
          }
        }
      ]
    ]);
  });

  it("uses the typed admin routes for the Skill runtime policy", async () => {
    const policy = {
      selective_activation_enabled: true,
      max_attached_skills: 100,
      context_share_percent: 10,
      max_activations_per_turn: 3,
      editable_bounds: {
        max_attached_skills: { minimum: 1, maximum: 1000 },
        context_share_percent: { minimum: 1, maximum: 100 },
        max_activations_per_turn: { minimum: 1, maximum: 10 }
      }
    };
    const projections = { context_share_percent: 10, models: [] };
    const fetch = vi.fn(async (endpoint) =>
      endpoint.endsWith("model-projections") ? projections : policy
    );
    const settings = initSettings({ fetch });

    await expect(settings.getSkillRuntimePolicy()).resolves.toBe(policy);
    await expect(settings.updateSkillRuntimePolicy(policy)).resolves.toBe(policy);
    await expect(settings.resetSkillRuntimePolicy()).resolves.toBe(policy);
    await expect(settings.getSkillRuntimeModelProjections()).resolves.toBe(projections);

    expect(fetch.mock.calls).toEqual([
      ["/api/v1/settings/skills/runtime-policy", { method: "get" }],
      [
        "/api/v1/settings/skills/runtime-policy",
        {
          method: "put",
          requestBody: {
            "application/json": {
              selective_activation_enabled: true,
              max_attached_skills: 100,
              context_share_percent: 10,
              max_activations_per_turn: 3
            }
          }
        }
      ],
      ["/api/v1/settings/skills/runtime-policy/reset", { method: "post" }],
      ["/api/v1/settings/skills/runtime-policy/model-projections", { method: "get" }]
    ]);
  });
});
