import type { Schema } from "@/lib/api/models";

export type SkillContent = Schema<"SkillRevisionCreateRequest">;
export type SkillCreation = Schema<"SkillCreateRequest">;

export function deriveSkillSlug(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
}

export function normalizedSkillContent(content: SkillContent): SkillContent {
  return {
    display_name: content.display_name.trim(),
    description: content.description.trim(),
    instructions: content.instructions.trim()
  };
}
