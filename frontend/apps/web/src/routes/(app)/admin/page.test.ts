import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

describe("Admin settings loader", () => {
  test("loads the tenant Skill runtime policy and model projections together", async () => {
    const skillRuntimePolicy = {
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
    const skillRuntimeModelProjections = {
      context_share_percent: 10,
      models: []
    };
    const getSkillRuntimePolicy = vi.fn().mockResolvedValue(skillRuntimePolicy);
    const getSkillRuntimeModelProjections = vi.fn().mockResolvedValue(skillRuntimeModelProjections);
    const event = {
      depends: vi.fn(),
      parent: vi.fn().mockResolvedValue({
        eneo: {
          settings: { getSkillRuntimePolicy, getSkillRuntimeModelProjections }
        }
      })
    };

    const result = await load(event as never);

    expect(getSkillRuntimePolicy).toHaveBeenCalledOnce();
    expect(getSkillRuntimeModelProjections).toHaveBeenCalledOnce();
    expect(result).toEqual({ skillRuntimePolicy, skillRuntimeModelProjections });
  });

  test("keeps policy settings available when model projections fail", async () => {
    const skillRuntimePolicy = { selective_activation_enabled: false };
    const event = {
      parent: vi.fn().mockResolvedValue({
        eneo: {
          settings: {
            getSkillRuntimePolicy: vi.fn().mockResolvedValue(skillRuntimePolicy),
            getSkillRuntimeModelProjections: vi.fn().mockRejectedValue(new Error("unavailable"))
          }
        }
      })
    };

    await expect(load(event as never)).resolves.toEqual({
      skillRuntimePolicy,
      skillRuntimeModelProjections: null
    });
  });
});
