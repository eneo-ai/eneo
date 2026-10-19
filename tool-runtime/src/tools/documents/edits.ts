// Targeted changes to a Markdown document: exact passages replaced in place, so a small change
// leaves the rest of the text as the user read it.
import { z } from "zod";
import { ToolError } from "../../errors";

export const MAX_EDITS = 20;
export const documentEdit = z
  .object({
    find: z
      .string()
      .min(1)
      .max(5000)
      .describe(
        "The exact text to replace, copied from the document's Markdown source with its punctuation and formatting marks.",
      ),
    replace: z.string().max(10_000).describe("The text that takes its place. Empty removes it."),
    occurrence: z
      .number()
      .int()
      .min(1)
      .optional()
      .describe("Which match to replace when the text occurs more than once, counted from 1."),
  })
  .strict();
export type DocumentEdit = z.infer<typeof documentEdit>;

const unixNewlines = (text: string) => text.replace(/\r\n?/g, "\n");

function matches(text: string, find: string): number[] {
  const at: number[] = [];
  for (let i = text.indexOf(find); i !== -1; i = text.indexOf(find, i + find.length)) at.push(i);
  return at;
}

/**
 * The document with each edit applied in order; a later edit sees the result of the earlier ones.
 * Every failure names the edit and says what to pass instead, so the caller can retry.
 */
export function applyEdits(source: string, edits: DocumentEdit[], maxChars: number): string {
  const original = unixNewlines(source);
  let text = original;
  edits.forEach((edit, index) => {
    const n = index + 1;
    const find = unixNewlines(edit.find);
    const found = matches(text, find);
    if (found.length === 0) {
      throw new ToolError(
        "EDIT_NOT_FOUND",
        `Edit ${n}: the text to find is not in the document. Copy it exactly from the document's Markdown source.`,
      );
    }
    if (edit.occurrence === undefined && found.length > 1) {
      throw new ToolError(
        "EDIT_AMBIGUOUS",
        `Edit ${n}: the text to find occurs ${found.length} times. Pass occurrence (1 to ${found.length}) or a longer passage that occurs once.`,
      );
    }
    const start = found[(edit.occurrence ?? 1) - 1];
    if (start === undefined) {
      throw new ToolError(
        "EDIT_OCCURRENCE",
        `Edit ${n}: occurrence ${edit.occurrence} was asked for, but the text occurs ${found.length} ${found.length === 1 ? "time" : "times"}.`,
      );
    }
    text = text.slice(0, start) + unixNewlines(edit.replace) + text.slice(start + find.length);
  });
  if (text === original) {
    throw new ToolError("EDIT_NO_CHANGE", "The edits leave the document as it was.");
  }
  if (text.length > maxChars) {
    throw new ToolError(
      "CONTENT_TOO_LONG",
      `The edited document is ${text.length} characters; the limit is ${maxChars}.`,
    );
  }
  return text;
}
