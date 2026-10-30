import type { VariableEntry, VariableGroup } from "./step-variables";

/**
 * When a template's editor offers references to complete, and what choosing
 * one writes: the reference editor's triggers (`flowPromptAutocomplete.ts` in
 * apps/web). `{{` opens the list until the reference is closed; `@` at the
 * start of a word opens it while no space follows. Caret arithmetic only:
 * what a reference reads is the reference grammar's (`readTarget`). Pure and
 * unit-tested.
 */

export type ReferenceTrigger = { kind: "braces" | "at"; start: number; query: string };

/** Where an unclosed `{{` before the caret starts, or null. */
function openBraces(text: string, caret: number): number | null {
  const before = text.slice(0, caret);
  const open = before.lastIndexOf("{{");
  if (open < 0 || before.lastIndexOf("}}") > open) return null;
  return open;
}

/** Where an `@` that starts a word before the caret is, with no space after it, or null. */
function openAt(text: string, caret: number): number | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/[\s([{]/.test(before[at - 1]!)) return null;
  if (/\s/.test(before.slice(at + 1))) return null;
  return at;
}

/**
 * The trigger at the caret. `{{` always opens it; `@` opens it as it is typed
 * (`typed`) and keeps it open while the caret stays in the word, so an `@` in
 * an e-mail address or one the caret only passes does not.
 */
export function triggerAt(
  text: string,
  caret: number,
  options: { typed: boolean; wasAt: boolean }
): ReferenceTrigger | null {
  const braces = openBraces(text, caret);
  if (braces !== null) {
    return { kind: "braces", start: braces, query: text.slice(braces + 2, caret).trim() };
  }
  if (!options.typed && !options.wasAt) return null;
  const at = openAt(text, caret);
  return at === null ? null : { kind: "at", start: at, query: text.slice(at + 1, caret) };
}

export type ReferenceSuggestion = { token: string; label: string };

/**
 * The references the step can read, named for the list (`label` names one
 * entry in its group), that match what was typed after the trigger: by name
 * or by the reference itself.
 */
export function referenceSuggestions(
  groups: readonly VariableGroup[],
  query: string,
  label: (entry: VariableEntry, group: VariableGroup) => string
): ReferenceSuggestion[] {
  const needle = query.trim().toLocaleLowerCase();
  return groups
    .flatMap((group) =>
      group.entries.map((entry) => ({ token: entry.token, label: label(entry, group) }))
    )
    .filter(
      (suggestion) =>
        !needle ||
        suggestion.label.toLocaleLowerCase().includes(needle) ||
        suggestion.token.toLocaleLowerCase().includes(needle)
    );
}

/** The text with the trigger and what was typed after it replaced by `{{token}}`, and the caret after it. */
export function completeReference(
  text: string,
  trigger: ReferenceTrigger,
  caret: number,
  token: string
): { text: string; caret: number } {
  const reference = `{{${token}}}`;
  return {
    text: text.slice(0, trigger.start) + reference + text.slice(closingEnd(text, trigger, caret)),
    caret: trigger.start + reference.length
  };
}

/** Where the replaced text ends: after the `}}` when the caret is inside a closed reference. */
function closingEnd(text: string, trigger: ReferenceTrigger, caret: number): number {
  if (trigger.kind !== "braces") return caret;
  const close = text.indexOf("}}", caret);
  if (close < 0) return caret;
  const rest = text.slice(caret, close);
  return rest.includes("{{") || rest.includes("\n") ? caret : close + 2;
}
