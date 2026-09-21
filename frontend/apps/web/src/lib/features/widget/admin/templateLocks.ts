import type { Widget, WidgetTemplate, WidgetTemplateLockGroup, WidgetTexts } from "@eneo/eneo-js";

/**
 * Which widget parts a template governs, mirroring the backend's
 * TemplateLockGroup. Groups map onto the editor's own sections, so a lock is
 * always a whole card or a named set of fields, never a surprise.
 */
export const LOCK_GROUPS: readonly WidgetTemplateLockGroup[] = [
  "appearance",
  "language",
  "legal_texts",
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

/** The text fields a widget following `link` cannot edit. */
export function lockedTextFields(
  link: Pick<NonNullable<Widget["template"]>, "locked_groups"> | null | undefined
): ReadonlySet<LockedTextField> {
  const locked = new Set<LockedTextField>();
  const groups = new Set(link?.locked_groups ?? []);
  if (groups.has("legal_texts")) for (const field of LEGAL_TEXT_FIELDS) locked.add(field);
  if (groups.has("wording")) for (const field of WORDING_FIELDS) locked.add(field);
  return locked;
}

export function isGroupLocked(
  link: Pick<NonNullable<Widget["template"]>, "locked_groups"> | null | undefined,
  group: WidgetTemplateLockGroup
): boolean {
  return (link?.locked_groups ?? []).includes(group);
}

type TemplateContent = Pick<WidgetTemplate, "texts" | "theme" | "language" | "locked_groups">;

/**
 * What a widget receives when it links to the template: the published
 * release, never the draft admins may still be editing. Only a template that
 * has never been published falls back to its draft, and pickers do not offer
 * those.
 */
export function templateRelease(template: WidgetTemplate): TemplateContent {
  return template.published ?? template;
}

function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item as Record<string, unknown>).sort())
      : item
  );
}

function groupDiffers(
  group: WidgetTemplateLockGroup,
  a: TemplateContent,
  b: TemplateContent
): boolean {
  switch (group) {
    case "appearance":
      return stableJson(a.theme) !== stableJson(b.theme);
    case "language":
      return a.language !== b.language;
    case "legal_texts":
      return LEGAL_TEXT_FIELDS.some((field) => (a.texts[field] ?? "") !== (b.texts[field] ?? ""));
    case "wording":
      return WORDING_FIELDS.some((field) => (a.texts[field] ?? "") !== (b.texts[field] ?? ""));
  }
}

export type PublicationSummary = {
  /** Parts replaced on every follower by this publication. */
  written: WidgetTemplateLockGroup[];
  /** Parts followers can no longer edit once this is published. */
  newlyLocked: WidgetTemplateLockGroup[];
  /** Parts followers may edit again once this is published. */
  released: WidgetTemplateLockGroup[];
  /** Changed parts the template does not lock: existing followers keep their own values. */
  changedUnlocked: WidgetTemplateLockGroup[];
};

/**
 * What publishing the draft does to the widgets that follow the template,
 * compared with the current release. Locked parts whose values did not change
 * are already on the followers, so they are not reported as written.
 */
export function publicationSummary(template: WidgetTemplate): PublicationSummary {
  const locked = new Set(template.locked_groups);
  const wasLocked = new Set(template.published?.locked_groups ?? []);
  const changed = (group: WidgetTemplateLockGroup) =>
    template.published == null || groupDiffers(group, template, template.published);
  return {
    written: LOCK_GROUPS.filter(
      (group) => locked.has(group) && (changed(group) || !wasLocked.has(group))
    ),
    newlyLocked: LOCK_GROUPS.filter((group) => locked.has(group) && !wasLocked.has(group)),
    released: LOCK_GROUPS.filter((group) => !locked.has(group) && wasLocked.has(group)),
    changedUnlocked: LOCK_GROUPS.filter((group) => !locked.has(group) && changed(group))
  };
}
