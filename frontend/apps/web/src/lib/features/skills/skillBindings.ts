import type {
  PublishedSkillSummaryPublic,
  SkillBindingReferenceInput,
  SkillBindingSummary,
  SkillPublic,
  SkillSparse
} from "@eneo/eneo-js";

export type SkillBindingSource = "space" | "organization";
export type SkillBindingCandidate =
  (SkillSparse & { source: "space" }) | (PublishedSkillSummaryPublic & { source: "organization" });

export type SkillRevisionFormValue = Pick<
  SkillPublic["current_revision"],
  "display_name" | "description" | "instructions"
>;

export type SkillFormValue = Pick<SkillPublic, "slug"> & SkillRevisionFormValue;

export type SkillBindingRevisionMetadata = {
  id: string;
  source: SkillBindingSource;
  slug: string;
  revisionId: string;
  revisionNumber: number;
  displayName: string;
  description: string;
};

export type SkillBindingRow = {
  reference: SkillBindingReferenceInput;
  summary: SkillBindingSummary | undefined;
  attachableRevisionId: string | undefined;
  attachableRevisionNumber: number | undefined;
  displayName: string | undefined;
  description: string | undefined;
  slug: string | undefined;
  source: SkillBindingSource | undefined;
  pinnedRevision: number | undefined;
  isActive: boolean | undefined;
  hasNewerRevision: boolean;
};

export function getAvailableSkills(
  catalog: SkillBindingCandidate[],
  bindings: SkillBindingReferenceInput[]
): SkillBindingCandidate[] {
  const boundSkillIds = new Set(bindings.map((binding) => binding.skill_id));
  return catalog.filter((skill) => isSkillCandidateActive(skill) && !boundSkillIds.has(skill.id));
}

export function appendSkillRevisionBinding(
  bindings: SkillBindingReferenceInput[],
  skill: { id: string; revisionId: string }
): SkillBindingReferenceInput[] {
  if (bindings.some((binding) => binding.skill_id === skill.id)) return bindings;

  return [
    ...bindings,
    {
      skill_id: skill.id,
      skill_revision_id: skill.revisionId
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
  skill: {
    id: string;
    attachableRevisionId: string;
    isActive: boolean;
  }
): SkillBindingReferenceInput[] {
  const binding = bindings[index];
  if (
    !binding ||
    binding.skill_id !== skill.id ||
    !skill.isActive ||
    binding.skill_revision_id === skill.attachableRevisionId
  ) {
    return bindings;
  }

  const upgraded = bindings.slice();
  upgraded[index] = {
    skill_id: binding.skill_id,
    skill_revision_id: skill.attachableRevisionId
  };
  return upgraded;
}

export function mergeSkillCatalog(
  catalog: SkillBindingCandidate[],
  additions: SkillBindingCandidate[]
): SkillBindingCandidate[] {
  const merged = new Map(catalog.map((skill) => [skill.id, skill]));
  for (const skill of additions) merged.set(skill.id, skill);
  return [...merged.values()];
}

export function getSkillBindingRows(
  bindings: SkillBindingReferenceInput[],
  summaries: SkillBindingSummary[],
  catalog: SkillBindingCandidate[],
  loadedRevisionMetadata: SkillBindingRevisionMetadata[] = []
): SkillBindingRow[] {
  const summariesByReference = new Map(
    summaries.map((summary) => [bindingKey(summary.skill_id, summary.skill_revision_id), summary])
  );
  const summariesBySkillId = new Map(summaries.map((summary) => [summary.skill_id, summary]));
  const catalogById = new Map(catalog.map((skill) => [skill.id, skill]));
  const metadataByReference = new Map(
    loadedRevisionMetadata.map((metadata) => [
      bindingKey(metadata.id, metadata.revisionId),
      metadata
    ])
  );

  return bindings.map((reference) => {
    const summary = summariesByReference.get(
      bindingKey(reference.skill_id, reference.skill_revision_id)
    );
    const skillSummary = summariesBySkillId.get(reference.skill_id);
    const currentSkill = catalogById.get(reference.skill_id);
    const attachableRevisionId =
      skillSummary?.attachable_revision_id ??
      (currentSkill === undefined ? undefined : getSkillCandidateRevisionId(currentSkill));
    const attachableRevisionNumber =
      skillSummary?.attachable_revision_number ??
      (currentSkill === undefined ? undefined : getSkillCandidateRevisionNumber(currentSkill));
    const referencesAttachableRevision = attachableRevisionId === reference.skill_revision_id;
    const loadedMetadata = metadataByReference.get(
      bindingKey(reference.skill_id, reference.skill_revision_id)
    );
    const currentSkillMatchesReference =
      currentSkill !== undefined &&
      getSkillCandidateRevisionId(currentSkill) === reference.skill_revision_id;
    const exactMetadata =
      summary === undefined
        ? (loadedMetadata ??
          (currentSkillMatchesReference
            ? {
                id: currentSkill.id,
                source: currentSkill.source,
                slug: currentSkill.slug,
                revisionId: getSkillCandidateRevisionId(currentSkill),
                revisionNumber: getSkillCandidateRevisionNumber(currentSkill),
                displayName: currentSkill.display_name,
                description: currentSkill.description
              }
            : undefined))
        : {
            id: summary.skill_id,
            source: summary.source,
            slug: summary.slug,
            revisionId: summary.skill_revision_id,
            revisionNumber: summary.revision_number,
            displayName: summary.display_name,
            description: summary.description
          };

    return {
      reference,
      summary,
      attachableRevisionId,
      attachableRevisionNumber,
      displayName:
        exactMetadata?.displayName ?? skillSummary?.display_name ?? currentSkill?.display_name,
      description:
        exactMetadata?.description ?? skillSummary?.description ?? currentSkill?.description,
      slug: exactMetadata?.slug ?? skillSummary?.slug ?? currentSkill?.slug,
      source: exactMetadata?.source ?? skillSummary?.source ?? currentSkill?.source,
      pinnedRevision:
        exactMetadata?.revisionNumber ??
        (referencesAttachableRevision ? attachableRevisionNumber : undefined),
      isActive:
        currentSkill !== undefined ? isSkillCandidateActive(currentSkill) : skillSummary?.is_active,
      hasNewerRevision: attachableRevisionId !== undefined && !referencesAttachableRevision
    };
  });
}

export function getSkillCandidateRevisionId(skill: SkillBindingCandidate): string {
  return skill.source === "space" ? skill.current_revision_id : skill.revision_id;
}

export function getSkillCandidateRevisionNumber(skill: SkillBindingCandidate): number {
  return skill.source === "space" ? skill.current_revision_number : skill.revision_number;
}

export function isSkillCandidateActive(skill: SkillBindingCandidate): boolean {
  return skill.source === "space" ? skill.is_active : true;
}

function bindingKey(skillId: string, revisionId: string): string {
  return `${skillId}:${revisionId}`;
}
