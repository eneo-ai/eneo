import type { Schema } from "@/lib/api/models";

export type Widget = Schema<"WidgetPublic">;
export type WidgetTemplate = Schema<"WidgetTemplatePublic">;
export type WidgetTemplateLockGroup = Schema<"TemplateLockGroup">;
export type WidgetTexts = Schema<"WidgetTexts">;

/**
 * Which widget parts a template governs, mirroring the backend's
 * TemplateLockGroup. Groups map onto the editor's own sections, so a lock is
 * always a whole card or a named set of fields, never a surprise.
 */
export const LOCK_GROUPS: readonly WidgetTemplateLockGroup[] = [
  "appearance",
  "language",
  "legal_texts",
  "persona",
  "wording"
];

export const LEGAL_TEXT_FIELDS = [
  "subtitle",
  "footer_text",
  "footer_link_url",
  "footer_link_label"
] as const satisfies readonly (keyof WidgetTexts)[];

export const WORDING_FIELDS = [
  "title",
  "welcome",
  "placeholder"
] as const satisfies readonly (keyof WidgetTexts)[];

export type LockedTextField = (typeof LEGAL_TEXT_FIELDS)[number] | (typeof WORDING_FIELDS)[number];

type Link = Pick<NonNullable<Widget["template"]>, "locked_groups"> | null | undefined;

/** The text fields a widget following `link` cannot edit. */
export function lockedTextFields(link: Link): ReadonlySet<LockedTextField> {
  const locked = new Set<LockedTextField>();
  const groups = new Set(link?.locked_groups ?? []);
  if (groups.has("legal_texts")) for (const field of LEGAL_TEXT_FIELDS) locked.add(field);
  if (groups.has("wording")) for (const field of WORDING_FIELDS) locked.add(field);
  return locked;
}

export function isGroupLocked(link: Link, group: WidgetTemplateLockGroup): boolean {
  return (link?.locked_groups ?? []).includes(group);
}

type TemplateContent = Pick<
  WidgetTemplate,
  "texts" | "theme" | "persona" | "language" | "locked_groups"
>;

/**
 * What a widget receives when it links to the template: the published
 * release, never the draft admins may still be editing. Only a template that
 * has never been published falls back to its draft, and pickers do not offer
 * those.
 */
export function templateRelease(template: WidgetTemplate): TemplateContent {
  return template.published ?? template;
}
