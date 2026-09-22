import type { SkillUsageCounts } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/** Whether any Assistant, App or Personal Chat still references the Skill. */
export function isSkillInUse(usage: SkillUsageCounts): boolean {
  return (
    usage.assistant_count > 0 ||
    usage.app_count > 0 ||
    usage.distinct_space_count > 0 ||
    usage.personal_chat_pinned
  );
}

/**
 * "2 assistenter · 1 app · 2 ytor" with Swedish and English plurals, or
 * `null` when nothing references the Skill so callers can show a quiet
 * "not in use" instead of three zeros.
 */
export function formatSkillUsage(usage: SkillUsageCounts): string | null {
  if (!isSkillInUse(usage)) return null;
  const count = (value: number) => ({ count: String(value) });
  return [
    usage.assistant_count === 1
      ? m.organization_skills_usage_assistants(count(1))
      : m.organization_skills_usage_assistants_plural(count(usage.assistant_count)),
    usage.app_count === 1
      ? m.organization_skills_usage_apps(count(1))
      : m.organization_skills_usage_apps_plural(count(usage.app_count)),
    usage.distinct_space_count === 1
      ? m.organization_skills_usage_spaces(count(1))
      : m.organization_skills_usage_spaces_plural(count(usage.distinct_space_count))
  ].join(" · ");
}
