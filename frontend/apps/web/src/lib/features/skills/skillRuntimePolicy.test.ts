import type { SkillRuntimePolicy } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import {
  isSkillRuntimePolicyDraftValid,
  skillRuntimePolicyDraft,
  skillRuntimePolicyDraftEquals
} from "./skillRuntimePolicy";

const policy: SkillRuntimePolicy = {
  selective_activation_enabled: true,
  max_attached_skills: 100,
  context_share_percent: 10,
  max_activations_per_turn: 3,
  editable_bounds: {
    max_attached_skills: { minimum: 2, maximum: 200 },
    context_share_percent: { minimum: 5, maximum: 40 },
    max_activations_per_turn: { minimum: 1, maximum: 6 }
  }
};

describe("Skill runtime policy draft", () => {
  test("derives the editable API payload without copying server-owned bounds", () => {
    expect(skillRuntimePolicyDraft(policy)).toEqual({
      selective_activation_enabled: true,
      max_attached_skills: 100,
      context_share_percent: 10,
      max_activations_per_turn: 3
    });
  });

  test("validates every number against the bounds returned by the backend", () => {
    const minimums = {
      selective_activation_enabled: false,
      max_attached_skills: 2,
      context_share_percent: 5,
      max_activations_per_turn: 1
    };
    const maximums = {
      selective_activation_enabled: true,
      max_attached_skills: 200,
      context_share_percent: 40,
      max_activations_per_turn: 6
    };

    expect(isSkillRuntimePolicyDraftValid(minimums, policy.editable_bounds)).toBe(true);
    expect(isSkillRuntimePolicyDraftValid(maximums, policy.editable_bounds)).toBe(true);
    expect(
      isSkillRuntimePolicyDraftValid(
        { ...minimums, context_share_percent: 4 },
        policy.editable_bounds
      )
    ).toBe(false);
    expect(
      isSkillRuntimePolicyDraftValid(
        { ...maximums, max_attached_skills: 201 },
        policy.editable_bounds
      )
    ).toBe(false);
  });

  test("rejects an emptied numeric field", () => {
    expect(
      isSkillRuntimePolicyDraftValid(
        { ...skillRuntimePolicyDraft(policy), context_share_percent: null },
        policy.editable_bounds
      )
    ).toBe(false);
  });

  test("compares the complete editable policy", () => {
    const draft = skillRuntimePolicyDraft(policy);

    expect(skillRuntimePolicyDraftEquals(draft, { ...draft })).toBe(true);
    expect(
      skillRuntimePolicyDraftEquals(draft, {
        ...draft,
        max_activations_per_turn: policy.max_activations_per_turn + 1
      })
    ).toBe(false);
  });
});
