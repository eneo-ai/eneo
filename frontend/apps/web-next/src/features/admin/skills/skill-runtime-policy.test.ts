import { describe, expect, it } from "vitest";
import {
  draftValid,
  draftsEqual,
  fieldValid,
  policyDraft,
  type SkillRuntimePolicy
} from "./skill-runtime-policy";

const policy: SkillRuntimePolicy = {
  selective_activation_enabled: false,
  max_attached_skills: 8,
  context_share_percent: 20,
  max_activations_per_turn: 3,
  editable_bounds: {
    max_attached_skills: { minimum: 1, maximum: 20 },
    context_share_percent: { minimum: 1, maximum: 50 },
    max_activations_per_turn: { minimum: 1, maximum: 10 }
  }
};

describe("skill runtime policy", () => {
  it("uses backend bounds for all three numeric fields", () => {
    expect(draftValid(policyDraft(policy), policy.editable_bounds)).toBe(true);
    expect(
      draftValid({ ...policyDraft(policy), context_share_percent: 51 }, policy.editable_bounds)
    ).toBe(false);
    expect(
      draftValid({ ...policyDraft(policy), max_attached_skills: null }, policy.editable_bounds)
    ).toBe(false);
    expect(fieldValid(2.5, policy.editable_bounds.max_activations_per_turn)).toBe(false);
  });

  it("detects every policy field independently", () => {
    const original = policyDraft(policy);
    expect(draftsEqual(original, policyDraft(policy))).toBe(true);
    expect(draftsEqual(original, { ...original, selective_activation_enabled: true })).toBe(false);
    expect(draftsEqual(original, { ...original, max_activations_per_turn: 4 })).toBe(false);
  });
});
