// Runs inside sandbox children only. Fills the {{placeholders}} of a template the user supplied
// with plain-text values. A Word template keeps everything else (styles, headers, footers, the
// formatting of the run a placeholder sits in); a text template is the same text with the
// placeholders replaced. Other ways to mark a field (Word content controls, mail-merge fields)
// are not read: a filler for one belongs beside these two.
import { PatchType, TextRun, patchDetector, patchDocument } from "docx";
import { ToolError } from "../../../errors";
import { openWordTemplate } from "./template";

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

/** Fills a Word template: body, headers and footers, also where Word split a placeholder. */
export async function fillDocx(template: Buffer, values: Values): Promise<Filled> {
  await openWordTemplate(template);
  const { names, valueOf } = resolve(await patchDetector({ data: template }), values);
  if (!names.length) return { buffer: template, placeholders: names };
  const patches = Object.fromEntries(
    [...valueOf].map(([placeholder, value]) => [
      placeholder,
      {
        type: PatchType.PARAGRAPH,
        children: value
          .split(/\r?\n/)
          .map((line, index) => new TextRun({ text: line, break: index > 0 ? 1 : undefined })),
      },
    ]),
  );
  const buffer = await patchDocument({
    outputType: "nodebuffer",
    data: template,
    patches,
    keepOriginalStyles: true,
  });
  return { buffer: Buffer.from(buffer), placeholders: names };
}

/** Fills a text template (plain text or Markdown). */
export function fillText(template: Buffer, values: Values): Filled {
  if (template.includes(0))
    throw new ToolError("INVALID_FILE", "The template is not a text file.");
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(template);
  } catch {
    throw new ToolError("INVALID_FILE", "Text templates must use UTF-8 encoding.");
  }
  const { names, valueOf } = resolve(
    [...text.matchAll(PLACEHOLDER)].map((match) => match[1]!),
    values,
  );
  return {
    buffer: Buffer.from(text.replace(PLACEHOLDER, (_, placeholder) => valueOf.get(placeholder)!)),
    placeholders: names,
  };
}
