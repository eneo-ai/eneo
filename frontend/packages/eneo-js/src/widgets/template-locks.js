// @ts-check
/** @typedef {import('../../index.js').Widget} Widget */
/** @typedef {import('../../index.js').WidgetTemplate} WidgetTemplate */
/** @typedef {import('../../index.js').WidgetTemplateLockGroup} WidgetTemplateLockGroup */
/** @typedef {(typeof LEGAL_TEXT_FIELDS)[number] | (typeof WORDING_FIELDS)[number]} LockedTextField */
/** @typedef {Pick<
 * WidgetTemplate,
 * "texts" | "theme" | "persona" | "language" | "locked_groups"
 * >} TemplateContent */
/**
 * @typedef {object} PublicationSummary
 * @property {WidgetTemplateLockGroup[]} written
 * @property {WidgetTemplateLockGroup[]} newlyLocked
 * @property {WidgetTemplateLockGroup[]} released
 * @property {WidgetTemplateLockGroup[]} changedUnlocked
 */
/**
 * Which widget parts a template governs, mirroring the backend's
 * TemplateLockGroup. Groups map onto the editor's own sections, so a lock is
 * always a whole card or a named set of fields, never a surprise.
 */
/** @type {readonly WidgetTemplateLockGroup[]} */
export const LOCK_GROUPS = ["appearance", "language", "legal_texts", "persona", "wording"];
export const LEGAL_TEXT_FIELDS = /** @type {const} */ ([
  "subtitle",
  "footer_text",
  "footer_link_url",
  "footer_link_label"
]);
export const WORDING_FIELDS = /** @type {const} */ (["title", "welcome", "placeholder"]);
/** The text fields a widget following `link` cannot edit. */
/** @param {Pick<NonNullable<Widget["template"]>, "locked_groups"> | null | undefined} link
 * @returns {ReadonlySet<LockedTextField>} */
export function lockedTextFields(link) {
  const locked = new Set();
  const groups = new Set(link?.locked_groups ?? []);
  if (groups.has("legal_texts")) for (const field of LEGAL_TEXT_FIELDS) locked.add(field);
  if (groups.has("wording")) for (const field of WORDING_FIELDS) locked.add(field);
  return locked;
}
/** @param {Pick<NonNullable<Widget["template"]>, "locked_groups"> | null | undefined} link
 * @param {WidgetTemplateLockGroup} group
 * @returns {boolean} */
export function isGroupLocked(link, group) {
  return (link?.locked_groups ?? []).includes(group);
}
/**
 * What a widget receives when it links to the template: the published
 * release, never the draft admins may still be editing. Only a template that
 * has never been published falls back to its draft, and pickers do not offer
 * those.
 */
/** @param {WidgetTemplate} template
 * @returns {TemplateContent} */
export function templateRelease(template) {
  return template.published ?? template;
}
/** @param {unknown} value
 * @returns {string} */
function stableJson(value) {
  return JSON.stringify(
    value,
    /** @param {unknown} item */ (_key, item) =>
      item && typeof item === "object" && !Array.isArray(item)
        ? Object.fromEntries(Object.entries(/** @type {Record<string, unknown>} */ (item)).sort())
        : item
  );
}
/** @param {WidgetTemplateLockGroup} group
 * @param {TemplateContent} a
 * @param {TemplateContent} b
 * @returns {boolean} */
function groupDiffers(group, a, b) {
  switch (group) {
    case "appearance":
      return stableJson(a.theme) !== stableJson(b.theme);
    case "language":
      return a.language !== b.language;
    case "legal_texts":
      return LEGAL_TEXT_FIELDS.some((field) => (a.texts[field] ?? "") !== (b.texts[field] ?? ""));
    case "persona":
      return stableJson(a.persona) !== stableJson(b.persona);
    case "wording":
      return WORDING_FIELDS.some((field) => (a.texts[field] ?? "") !== (b.texts[field] ?? ""));
  }
}
/**
 * What publishing the draft does to the widgets that follow the template,
 * compared with the current release. Locked parts whose values did not change
 * are already on the followers, so they are not reported as written.
 */
/** @param {WidgetTemplate} template
 * @returns {PublicationSummary} */
export function publicationSummary(template) {
  const locked = new Set(template.locked_groups);
  const wasLocked = new Set(template.published?.locked_groups ?? []);
  const changed = /** @param {WidgetTemplateLockGroup} group */ (group) =>
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
