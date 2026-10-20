// Runs inside sandbox children only. Fills the {{placeholders}} of a text template (plain
// text or Markdown) with plain-text values: the same text with the placeholders replaced.
// Word templates are filled in word/apply.ts, which also reads content controls.
import { ToolError } from "../../../errors";

/** Placeholder name to the text that replaces it. */
export type Values = Record<string, string>;
/** The filled template and the names of the placeholders it had. */
export type Filled = { buffer: Buffer; placeholders: string[] };

const PLACEHOLDER = /\{\{(.+?)\}\}/g;

/**
 * The value for each placeholder as written in the template (`{{ namn }}` is `namn`). A
 * placeholder without a value is refused, with the names listed so the caller can supply them.
 */
function resolve(
  written: readonly string[],
  values: Values,
): { names: string[]; valueOf: Map<string, string> } {
  const given = new Map(Object.entries(values).map(([name, value]) => [name.trim(), value]));
  const names = [...new Set(written.map((placeholder) => placeholder.trim()))];
  const missing = names.filter((name) => !given.has(name));
  if (missing.length)
    throw new ToolError(
      "TEMPLATE_VALUES_MISSING",
      `The template has these placeholders: ${names.join(", ")}. No value was given for: ${missing.join(", ")}. Pass a value for each, named exactly as listed; an empty string leaves one blank. Ask the user for a value you do not know.`,
    );
  return {
    names,
    valueOf: new Map(written.map((placeholder) => [placeholder, given.get(placeholder.trim())!])),
  };
}

/** The placeholder names of a text template, each once, in order of appearance. */
export function textPlaceholders(template: Buffer): string[] {
  return [...new Set([...decode(template).matchAll(PLACEHOLDER)].map((m) => m[1]!.trim()))];
}

function decode(template: Buffer): string {
  if (template.includes(0)) throw new ToolError("INVALID_FILE", "The template is not a text file.");
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(template);
  } catch {
    throw new ToolError("INVALID_FILE", "Text templates must use UTF-8 encoding.");
  }
}

/** Fills a text template (plain text or Markdown). */
export function fillText(template: Buffer, values: Values): Filled {
  const text = decode(template);
  const { names, valueOf } = resolve(
    [...text.matchAll(PLACEHOLDER)].map((match) => match[1]!),
    values,
  );
  return {
    buffer: Buffer.from(text.replace(PLACEHOLDER, (_, placeholder) => valueOf.get(placeholder)!)),
    placeholders: names,
  };
}
