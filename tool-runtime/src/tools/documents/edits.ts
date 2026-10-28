// Targeted changes to a Markdown document: exact passages replaced in place, so a small change
// leaves the rest of the text as the user read it.
//
// The model copies the text to find from the document as it remembers it, and that differs
// from the stored text in known ways: an image it placed as ![alt](image:ID) is stored as
// ![alt](eneo-file:…) with its caption, and a version saved from the editor pads its table
// cells. A match looks past those differences; the replacement is made in the stored text.
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
        "The exact text to replace, copied from the document's Markdown source with its punctuation and formatting marks. An image stands in the document as ![alt text](eneo-file:…) whatever marker placed it, and a table's cell padding does not matter.",
      ),
    replace: z
      .string()
      .max(10_000)
      .describe(
        "The text that takes its place. Empty removes it. An image that stays keeps the document's own ![alt text](eneo-file:…) line.",
      ),
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

/** An image as the tools place it (image:ID) or as the document stores it (eneo-file:…). */
const IMAGE =
  /!\[([^\]\n]*)\]\((image:[A-Za-z][A-Za-z0-9_-]{0,63}|eneo-file:[0-9a-f]{32})([ \t]+"(?:[^"\\\n]|\\.)*")?\)/g;
const TABLE_ROW = /^[ \t]*\|/;
const SEPARATOR_ROW = /^[ \t]*\|?[ \t:|-]*-[ \t:|-]*\|?[ \t]*$/;

/**
 * A text with the known differences taken out, each character mapped back to the span of
 * the original it stands for: `from[i]` is where character i starts, `to[i]` where it ends.
 */
type View = { text: string; from: number[]; to: number[] };

function view(original: string): View {
  const text: string[] = [];
  const from: number[] = [];
  const to: number[] = [];
  // `chunk` stands for original[start, end). Character for character when the lengths agree,
  // else every character stands for the whole span.
  const emit = (chunk: string, start: number, end: number) => {
    const exact = chunk.length === end - start;
    for (let j = 0; j < chunk.length; j++) {
      text.push(chunk[j]!);
      from.push(exact ? start + j : start);
      to.push(exact ? start + j + 1 : end);
    }
  };
  const emitProse = (line: string, start: number) => {
    let last = 0;
    for (const match of line.matchAll(IMAGE)) {
      const at = match.index;
      emit(line.slice(last, at), start + last, start + at);
      const open = at + match[0].indexOf("](") + 1;
      emit(line.slice(at, open), start + at, start + open);
      emit("(image)", start + open, start + at + match[0].length);
      last = at + match[0].length;
    }
    emit(line.slice(last), start + last, start + line.length);
  };
  const emitRow = (line: string, start: number, separator: boolean) => {
    let i = 0;
    while (i < line.length) {
      const char = line[i]!;
      if (char === " " || char === "\t") {
        i += 1;
      } else if (char === "|" || (separator && char === ":")) {
        emit(char, start + i, start + i + 1);
        i += 1;
      } else if (separator && char === "-") {
        let end = i;
        while (line[end] === "-") end += 1;
        emit("-", start + i, start + end);
        i = end;
      } else {
        // A cell's text, up to the next pipe, with its inner spacing as written.
        let end = i;
        while (end < line.length && line[end] !== "|") end += 1;
        const cell = line.slice(i, end).replace(/[ \t]+$/, "");
        emitProse(cell, start + i);
        i = end;
      }
    }
  };
  let lineStart = 0;
  for (;;) {
    const newline = original.indexOf("\n", lineStart);
    const lineEnd = newline === -1 ? original.length : newline;
    const line = original.slice(lineStart, lineEnd).replace(/[ \t]+$/, "");
    if (TABLE_ROW.test(line)) emitRow(line, lineStart, SEPARATOR_ROW.test(line));
    else emitProse(line, lineStart);
    if (newline === -1) break;
    emit("\n", newline, newline + 1);
    lineStart = newline + 1;
  }
  return { text: text.join(""), from, to };
}

function matches(text: string, find: string): number[] {
  const at: number[] = [];
  for (let i = text.indexOf(find); i !== -1; i = text.indexOf(find, i + find.length)) at.push(i);
  return at;
}

/**
 * The replacement with each ![alt](image:ID) marker it places pointed at the image the
 * replaced text already holds, so an image keeps its handle and caption under the alt text
 * the replacement gives it.
 */
function placeImages(replace: string, replaced: string, n: number): string {
  const available = [...replaced.matchAll(IMAGE)];
  return replace.replace(IMAGE, (marker: string, alt: string, destination: string) => {
    if (!destination.startsWith("image:")) return marker;
    const sameAlt = available.findIndex((image) => image[1] === alt);
    const index = sameAlt !== -1 ? sameAlt : available.length === 1 ? 0 : -1;
    if (index === -1)
      throw new ToolError(
        "EDIT_IMAGE_UNKNOWN",
        `Edit ${n}: the replacement places ${destination}, but the text it replaces holds no such image. Keep an image as the document's own ![alt text](eneo-file:…) line. To add an image, revise the document with create_document and declare it in images.`,
      );
    const [, , handle, caption = ""] = available.splice(index, 1)[0]!;
    return `![${alt}](${handle}${caption})`;
  });
}

const LOOSE_MAX = 600;

/**
 * The lines of the document around the text that comes closest to `find`: the lines holding
 * its image's alt text, else the longest opening run of its words found in the document,
 * compared without regard to case or spacing. Undefined when nothing in the document resembles it.
 */
export function nearestPassage(document: string, find: string): string | undefined {
  const loose = (text: string) => {
    const out: string[] = [];
    const at: number[] = [];
    let space = true;
    for (let i = 0; i < text.length; i++) {
      const char = text[i]!;
      if (/\s/.test(char)) {
        if (!space) {
          out.push(" ");
          at.push(i);
        }
        space = true;
        continue;
      }
      space = false;
      const lower = char.toLowerCase();
      out.push(lower.length === 1 ? lower : char);
      at.push(i);
    }
    return { text: out.join("").trim(), at };
  };
  const haystack = loose(document);
  const needles: string[] = [];
  for (const image of find.matchAll(IMAGE)) if (image[1]) needles.push(image[1]);
  const words = find.split(/\s+/).filter(Boolean);
  for (let n = Math.min(words.length, 8); n >= 1; n--) {
    const needle = words.slice(0, n).join(" ");
    if (n > 1 || needle.length >= 4) needles.push(needle);
  }
  for (const raw of needles) {
    const needle = loose(raw).text;
    if (!needle) continue;
    const at = haystack.text.indexOf(needle);
    if (at === -1) continue;
    const start = document.lastIndexOf("\n", haystack.at[at]!) + 1;
    const lastChar = haystack.at[at + needle.length - 1]!;
    const newline = document.indexOf("\n", lastChar);
    const end = newline === -1 ? document.length : newline;
    const passage = document.slice(start, end);
    return passage.length > LOOSE_MAX ? `${passage.slice(0, LOOSE_MAX)}…` : passage;
  }
  return undefined;
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
    const find = view(unixNewlines(edit.find));
    const document = view(text);
    const found = find.text ? matches(document.text, find.text) : [];
    if (found.length === 0) {
      const nearest = nearestPassage(text, unixNewlines(edit.find));
      throw new ToolError(
        "EDIT_NOT_FOUND",
        `Edit ${n}: the text to find is not in the document. Copy it exactly from the document's Markdown source.` +
          (nearest
            ? ` The nearest passage in the document reads:\n${nearest}`
            : " Read the document to see its current text."),
      );
    }
    if (edit.occurrence === undefined && found.length > 1) {
      throw new ToolError(
        "EDIT_AMBIGUOUS",
        `Edit ${n}: the text to find occurs ${found.length} times. Pass occurrence (1 to ${found.length}) or a longer passage that occurs once.`,
      );
    }
    const at = found[(edit.occurrence ?? 1) - 1];
    if (at === undefined) {
      throw new ToolError(
        "EDIT_OCCURRENCE",
        `Edit ${n}: occurrence ${edit.occurrence} was asked for, but the text occurs ${found.length} ${found.length === 1 ? "time" : "times"}.`,
      );
    }
    const start = document.from[at]!;
    const end = document.to[at + find.text.length - 1]!;
    const replacement = placeImages(unixNewlines(edit.replace), text.slice(start, end), n);
    text = text.slice(0, start) + replacement + text.slice(end);
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
