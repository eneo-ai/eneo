import type { Schema } from "@/lib/api/models";

export type OrganizationSkill = Schema<"OrganizationSkillSummaryPublic">;
export type SkillRemovalRequest = Schema<"SkillRemovalRequest">;
export type SkillRemovalResult = Schema<"SkillRemovalPublic">;
export type SkillUsage = Schema<"SkillUsageCountsPublic">;

export const ORGANIZATION_SKILLS_KEY = ["organization-skills"] as const;
export const SKILL_SELECTION_LIMIT = 100;

export function isSkillInUse(usage: SkillUsage): boolean {
  return (
    usage.assistant_count > 0 ||
    usage.app_count > 0 ||
    usage.distinct_space_count > 0 ||
    usage.personal_chat_pinned
  );
}

/** The removal endpoint requires detach approval for these live bindings. */
export function removalBlocked(usage: SkillUsage): boolean {
  return usage.assistant_count > 0 || usage.app_count > 0 || usage.personal_chat_pinned;
}

export function selectedSkills(
  items: readonly OrganizationSkill[],
  ids: readonly string[]
): OrganizationSkill[] {
  const selected = new Set(ids);
  return items.filter((item) => selected.has(item.id)).slice(0, SKILL_SELECTION_LIMIT);
}

export function removalRequest(
  skills: readonly OrganizationSkill[],
  detachBindings: boolean,
  serverBlockedIds: readonly string[] = []
): SkillRemovalRequest | null {
  if (skills.length === 0 || skills.length > SKILL_SELECTION_LIMIT) return null;
  const blocked = new Set(serverBlockedIds);
  const hasBindings = skills.some((skill) => removalBlocked(skill.usage) || blocked.has(skill.id));
  if (hasBindings && !detachBindings) return null;
  return {
    skill_ids: skills.map((skill) => skill.id),
    detach_bindings: hasBindings && detachBindings
  };
}

export function serverBlockingIds(details: unknown): string[] {
  if (typeof details !== "object" || details === null || !("skill_ids" in details)) return [];
  const ids = details.skill_ids;
  return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [];
}
