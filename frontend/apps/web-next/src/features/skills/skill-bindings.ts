import type { Schema } from "@/lib/api/models";
import { candidateRevisionId, type SkillCandidate } from "./skill-binding-catalog";

export type Binding = Schema<"AssistantSkillBindingInput">;
export type BindingSummary = Schema<"AssistantSkillBindingSummary"> | Schema<"SkillBindingSummary">;

/** The saved order and exact revision IDs are the resource's Skill contract. */
export function bindingsFromSummaries(summaries: BindingSummary[]): Binding[] {
  return [...summaries]
    .sort((left, right) => left.position - right.position)
    .map((summary) => ({
      skill_id: summary.skill_id,
      skill_revision_id: summary.skill_revision_id,
      ...("activation_mode" in summary ? { activation_mode: summary.activation_mode } : {})
    }));
}

export function appendBinding(
  bindings: Binding[],
  skill: SkillCandidate,
  assistant: boolean
): Binding[] {
  if (bindings.some((binding) => binding.skill_id === skill.id)) return bindings;
  return [
    ...bindings,
    {
      skill_id: skill.id,
      skill_revision_id: candidateRevisionId(skill),
      ...(assistant ? { activation_mode: "always" as const } : {})
    }
  ];
}

export function moveBinding(bindings: Binding[], index: number, direction: -1 | 1): Binding[] {
  const destination = index + direction;
  if (index < 0 || destination < 0 || index >= bindings.length || destination >= bindings.length)
    return bindings;
  const result = [...bindings];
  const current = result[index];
  const adjacent = result[destination];
  if (!current || !adjacent) return bindings;
  result[index] = adjacent;
  result[destination] = current;
  return result;
}

export function removeBinding(bindings: Binding[], skillId: string): Binding[] {
  return bindings.filter((binding) => binding.skill_id !== skillId);
}

export function reviseBinding(bindings: Binding[], skillId: string, revisionId: string): Binding[] {
  return bindings.map((binding) =>
    binding.skill_id === skillId ? { ...binding, skill_revision_id: revisionId } : binding
  );
}

export function activateBinding(
  bindings: Binding[],
  skillId: string,
  mode: Schema<"SkillActivationMode">
): Binding[] {
  return bindings.map((binding) =>
    binding.skill_id === skillId ? { ...binding, activation_mode: mode } : binding
  );
}

export function appBindingPayload(bindings: Binding[]): Schema<"SkillBindingReferenceInput">[] {
  return bindings.map(({ skill_id, skill_revision_id }) => ({ skill_id, skill_revision_id }));
}
