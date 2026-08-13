import type { SkillBindingReferenceInput } from "@eneo/eneo-js";

type SkillBindingChange<TBinding extends SkillBindingReferenceInput> = {
  skill_bindings?: TBinding[];
};

export function mergeParentSkillBindings<
  T extends { id: string },
  TBinding extends SkillBindingReferenceInput
>(
  updated: T,
  persistedBindings: TBinding[],
  changes: SkillBindingChange<TBinding>
): T & { skill_bindings: TBinding[] } {
  return {
    ...updated,
    skill_bindings: changes.skill_bindings ?? persistedBindings
  };
}
