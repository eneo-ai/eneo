import type {
  SkillBindingReferenceInput,
  SkillBindingSummary,
  SkillPublic,
  SkillSparse
} from "@eneo/eneo-js";

export type SkillRevisionFormValue = Pick<
  SkillPublic["current_revision"],
  "display_name" | "description" | "instructions"
>;

export type SkillFormValue = Pick<SkillPublic, "slug"> & SkillRevisionFormValue;

export type SkillBindingRow = {
  reference: SkillBindingReferenceInput;
  summary: SkillBindingSummary | undefined;
  currentSkill: SkillSparse | undefined;
  displayName: string | undefined;
  description: string | undefined;
  pinnedRevision: number | undefined;
  isActive: boolean | undefined;
  hasNewerRevision: boolean;
};

export function getAvailableSkills(
  catalog: SkillSparse[],
  bindings: SkillBindingReferenceInput[]
): SkillSparse[] {
  const boundSkillIds = new Set(bindings.map((binding) => binding.skill_id));
  return catalog.filter((skill) => skill.is_active && !boundSkillIds.has(skill.id));
}

export function appendSkillBinding(
  bindings: SkillBindingReferenceInput[],
  skill: SkillSparse
): SkillBindingReferenceInput[] {
  if (bindings.some((binding) => binding.skill_id === skill.id)) return bindings;

  return [
    ...bindings,
    {
      skill_id: skill.id,
      skill_revision_id: skill.current_revision_id
    }
  ];
}

export function removeSkillBinding(
  bindings: SkillBindingReferenceInput[],
  skillId: string
): SkillBindingReferenceInput[] {
  return bindings.filter((binding) => binding.skill_id !== skillId);
}

export function moveSkillBinding(
  bindings: SkillBindingReferenceInput[],
  index: number,
  direction: "up" | "down"
): SkillBindingReferenceInput[] {
  const destination = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || index >= bindings.length || destination < 0 || destination >= bindings.length) {
    return bindings;
  }

  const reordered = bindings.slice();
  [reordered[index], reordered[destination]] = [reordered[destination], reordered[index]];
  return reordered;
}

export function upgradeSkillBinding(
  bindings: SkillBindingReferenceInput[],
  index: number,
  currentSkill: SkillSparse
): SkillBindingReferenceInput[] {
  const binding = bindings[index];
  if (
    !binding ||
    binding.skill_id !== currentSkill.id ||
    !currentSkill.is_active ||
    binding.skill_revision_id === currentSkill.current_revision_id
  ) {
    return bindings;
  }

  const upgraded = bindings.slice();
  upgraded[index] = {
    skill_id: binding.skill_id,
    skill_revision_id: currentSkill.current_revision_id
  };
  return upgraded;
}

export function mergeSkillCatalog(catalog: SkillSparse[], additions: SkillPublic[]): SkillSparse[] {
  const merged = new Map(catalog.map((skill) => [skill.id, skill]));
  for (const skill of additions) merged.set(skill.id, skill);
  return [...merged.values()];
}

export function getSkillBindingRows(
  bindings: SkillBindingReferenceInput[],
  summaries: SkillBindingSummary[],
  catalog: SkillSparse[]
): SkillBindingRow[] {
  const summariesByReference = new Map(
    summaries.map((summary) => [bindingKey(summary.skill_id, summary.skill_revision_id), summary])
  );
  const catalogById = new Map(catalog.map((skill) => [skill.id, skill]));

  return bindings.map((reference) => {
    const summary = summariesByReference.get(
      bindingKey(reference.skill_id, reference.skill_revision_id)
    );
    const currentSkill = catalogById.get(reference.skill_id);
    const referencesCurrentRevision =
      currentSkill?.current_revision_id === reference.skill_revision_id;

    return {
      reference,
      summary,
      currentSkill,
      displayName: summary?.display_name ?? currentSkill?.display_name,
      description: summary?.description ?? currentSkill?.description,
      pinnedRevision:
        summary?.revision_number ??
        (referencesCurrentRevision ? currentSkill.current_revision_number : undefined),
      isActive: currentSkill?.is_active ?? summary?.is_active,
      hasNewerRevision: currentSkill !== undefined && !referencesCurrentRevision
    };
  });
}

function bindingKey(skillId: string, revisionId: string): string {
  return `${skillId}:${revisionId}`;
}
