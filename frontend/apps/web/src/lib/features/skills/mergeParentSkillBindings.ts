import type { SkillBindingReferenceInput } from "@eneo/eneo-js";

type SkillBindingChange = {
  skill_bindings?: SkillBindingReferenceInput[];
};

export function mergeParentSkillBindings<T extends { id: string }>(
  updated: T,
  persistedBindings: SkillBindingReferenceInput[],
  changes: SkillBindingChange
): T & { skill_bindings: SkillBindingReferenceInput[] } {
  return {
    ...updated,
    skill_bindings: changes.skill_bindings ?? persistedBindings
  };
}
