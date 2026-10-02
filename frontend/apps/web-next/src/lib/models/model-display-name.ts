/**
 * One name for a model wherever it is shown: the admin's nickname (or the
 * catalog's display name) when there is one, otherwise the id made readable.
 * Lists then no longer mix "Claude Haiku 4.5" with "claude-haiku-4-5". Admin
 * tables show the raw id as a secondary line when it differs (`modelTechnicalId`).
 */
export type ModelNameSource = {
  name: string;
  nickname?: string | null;
  display_name?: string | null;
};

/** Ids made of lowercase words and short version numbers, like `claude-haiku-4-5`. */
const SAFE_ID = /^[a-z]+(?:-(?:[a-z]+|\d{1,2}))*$/;
/** Lowercase tokens whose readable form is not a capitalised word. */
const ACRONYMS: Record<string, string> = { gpt: "GPT", ai: "AI" };

export function modelDisplayName(model: ModelNameSource): string {
  const chosen = model.nickname?.trim() || model.display_name?.trim();
  return chosen || humaniseModelId(model.name);
}

/**
 * `claude-haiku-4-5` → "Claude Haiku 4.5", `gpt-4-turbo` → "GPT-4 Turbo",
 * `mistral-large` → "Mistral Large". Ids with dates, sizes, paths or mixed
 * tokens (`gpt-4o`, `llama-3-70b`, `text-embedding-3-small-2024`) are kept
 * as they are: a wrong guess would mislead more than the raw id.
 */
export function humaniseModelId(id: string): string {
  const trimmed = id.trim();
  if (!SAFE_ID.test(trimmed)) return trimmed;
  const words: string[] = [];
  for (const token of trimmed.split("-")) {
    const previous = words[words.length - 1];
    if (/^\d+$/.test(token) && previous !== undefined && /^\d+(\.\d+)*$/.test(previous)) {
      // A second version number: 4, 5 → 4.5
      words[words.length - 1] = `${previous}.${token}`;
    } else if (/^\d+$/.test(token) && previous !== undefined && /-\d+$/.test(previous)) {
      words[words.length - 1] = `${previous}.${token}`;
    } else if (/^\d+$/.test(token) && previous !== undefined && isAcronym(previous)) {
      // Vendors write the version onto the acronym: GPT-4, GPT-5
      words[words.length - 1] = `${previous}-${token}`;
    } else if (/^\d+$/.test(token)) {
      words.push(token);
    } else {
      words.push(ACRONYMS[token] ?? token.charAt(0).toUpperCase() + token.slice(1));
    }
  }
  return words.join(" ");
}

function isAcronym(word: string): boolean {
  return Object.values(ACRONYMS).includes(word);
}

/** The raw id for a secondary line in admin tables; null when it is the name shown. */
export function modelTechnicalId(model: ModelNameSource): string | null {
  return model.name !== modelDisplayName(model) ? model.name : null;
}
