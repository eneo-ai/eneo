import { modelDisplayName, type ModelNameSource } from "@/lib/models/model-display-name";

/**
 * What an editor's sections hold now, in a few words, for the rows of its
 * phone index (decision 21): "3 källor", "257 tecken", "Utkast".
 */
type Translate = (key: string, values?: Record<string, string | number>) => string;

/** A description's first words: the row shows one line, and is read whole. */
const DESCRIPTION_LENGTH = 40;

export function editorSummaries(t: Translate) {
  const count = (n: number, some: string, none: string) =>
    n > 0 ? t(some, { count: n }) : t(none);
  return {
    description: (text?: string | null) => {
      const line = text?.trim().replace(/\s+/g, " ") ?? "";
      if (!line) return t("editor_summary_no_description");
      // By characters, so an emoji at the cut is never split in two.
      const characters = Array.from(line);
      return characters.length > DESCRIPTION_LENGTH
        ? `${characters.slice(0, DESCRIPTION_LENGTH).join("").trimEnd()}…`
        : line;
    },
    instructions: (text?: string | null) =>
      count(
        text?.trim().length ?? 0,
        "editor_summary_characters",
        "editor_summary_no_instructions"
      ),
    sources: (n: number) => count(n, "editor_summary_sources", "editor_summary_no_sources"),
    chosen: (n: number) => count(n, "editor_summary_chosen", "editor_summary_none_chosen"),
    files: (n: number) => count(n, "editor_summary_files", "editor_summary_none"),
    retention: (days?: number | null) =>
      days ? t("editor_summary_retention", { count: days }) : t("editor_summary_space_retention"),
    model: (model?: ModelNameSource | null) => (model ? modelDisplayName(model) : undefined),
    publishing: (published?: boolean) => t(published ? "published" : "draft")
  };
}
