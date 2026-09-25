import type {
  SkillRuntimeModelProjections,
  SkillRuntimePolicy,
  SkillRuntimePolicyUpdate
} from "@eneo/eneo-js";

type SkillRuntimePolicyBounds = SkillRuntimePolicy["editable_bounds"];

export type SkillRuntimePolicyDraft = Omit<
  SkillRuntimePolicyUpdate,
  "max_attached_skills" | "context_share_percent" | "max_activations_per_turn"
> & {
  max_attached_skills: number | null;
  context_share_percent: number | null;
  max_activations_per_turn: number | null;
};

export type SkillRuntimePolicySnapshot = {
  policy: SkillRuntimePolicy;
  modelProjections: SkillRuntimeModelProjections | null;
};

export function skillRuntimePolicyDraft(policy: SkillRuntimePolicy): SkillRuntimePolicyDraft {
  return {
    selective_activation_enabled: policy.selective_activation_enabled,
    max_attached_skills: policy.max_attached_skills,
    context_share_percent: policy.context_share_percent,
    max_activations_per_turn: policy.max_activations_per_turn
  };
}

export function isSkillRuntimePolicyFieldValid(
  value: number | null,
  bounds: { minimum: number; maximum: number }
): value is number {
  return (
    value !== null && Number.isInteger(value) && value >= bounds.minimum && value <= bounds.maximum
  );
}

export function isSkillRuntimePolicyDraftValid(
  draft: SkillRuntimePolicyDraft,
  bounds: SkillRuntimePolicyBounds
): draft is SkillRuntimePolicyUpdate {
  return (
    isSkillRuntimePolicyFieldValid(draft.max_attached_skills, bounds.max_attached_skills) &&
    isSkillRuntimePolicyFieldValid(draft.context_share_percent, bounds.context_share_percent) &&
    isSkillRuntimePolicyFieldValid(draft.max_activations_per_turn, bounds.max_activations_per_turn)
  );
}

export function skillRuntimePolicyDraftEquals(
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
