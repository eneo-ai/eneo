import type { Schema } from "@/lib/api/models";

export type SkillRuntimePolicy = Schema<"SkillRuntimePolicyPublic">;
export type SkillRuntimePolicyUpdate = Schema<"SkillRuntimePolicyUpdate">;
export type SkillRuntimeModelProjections = Schema<"SkillRuntimeModelProjections">;
export type SkillRuntimePolicyDraft = {
  selective_activation_enabled: boolean;
  max_attached_skills: number | null;
  context_share_percent: number | null;
  max_activations_per_turn: number | null;
};

export function policyDraft(policy: SkillRuntimePolicy): SkillRuntimePolicyDraft {
  return {
    selective_activation_enabled: policy.selective_activation_enabled,
    max_attached_skills: policy.max_attached_skills,
    context_share_percent: policy.context_share_percent,
    max_activations_per_turn: policy.max_activations_per_turn
  };
}

export function fieldValid(
  value: number | null,
  bounds: { minimum: number; maximum: number }
): value is number {
  return (
    value !== null && Number.isInteger(value) && value >= bounds.minimum && value <= bounds.maximum
  );
}

export function draftValid(
  draft: SkillRuntimePolicyDraft,
  bounds: SkillRuntimePolicy["editable_bounds"]
): draft is SkillRuntimePolicyUpdate {
  return (
    fieldValid(draft.max_attached_skills, bounds.max_attached_skills) &&
    fieldValid(draft.context_share_percent, bounds.context_share_percent) &&
    fieldValid(draft.max_activations_per_turn, bounds.max_activations_per_turn)
  );
}

export function draftsEqual(
  left: SkillRuntimePolicyDraft,
  right: SkillRuntimePolicyDraft
): boolean {
  return (
    left.selective_activation_enabled === right.selective_activation_enabled &&
    left.max_attached_skills === right.max_attached_skills &&
    left.context_share_percent === right.context_share_percent &&
    left.max_activations_per_turn === right.max_activations_per_turn
  );
}
