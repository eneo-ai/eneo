import { isLocator } from "$lib/features/file-preview/selection";

/**
 * A quote from a file, carried in the text of a question.
 *
 * The quote travels as the opening lines of the question, in a form both the
 * model and the question bubble read without knowing the UI language:
 *
 *     > the quoted text,
 *     > line by line
 *     > (name of the file.docx, occurrence 2 of 5)
 *
 *     what the user asks about it
 *
 * The part after the file name is the locator: it says which of several
 * identical passages was selected, and is left out when the text is unique.
 */
export type QuestionQuote = {
  text: string;
  /** Exact immutable file, when supplied by the preview. */
  fileId?: string;
  /** The file the text was selected in, when the quote names one. */
  fileName: string | null;
  /** Which of several identical passages in the file is meant. */
  locator: string | null;
};

const QUOTE_LINE = /^>( |$)/;
const SOURCE_LINE = /^\((.+)\)$/;
const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FILE_LOCATOR = /^file ([0-9a-f-]{36})(?:; (.*))?$/i;

/** The text to send for a question that quotes a file. */
export function composeQuotedQuestion(
  quote: { text: string; fileName: string; fileId?: string; locator: string | null } | null,
  question: string
): string {
  if (!quote) return question;
  const identity =
    quote.fileId && FILE_ID.test(quote.fileId) ? `file ${quote.fileId.toLowerCase()}` : "";
  const locator = [identity, quote.locator].filter(Boolean).join("; ");
  const source = locator ? `${quote.fileName}, ${locator}` : quote.fileName;
  const quoted = [...quote.text.split("\n"), `(${source})`]
    .map((line) => (line === "" ? ">" : `> ${line}`))
    .join("\n");
  return question === "" ? quoted : `${quoted}\n\n${question}`;
}

/** Splits a question into the quote it opens with, if any, and the rest. */
export function parseQuotedQuestion(question: string): {
  quote: QuestionQuote | null;
  text: string;
} {
  const lines = question.split("\n");
  let end = 0;
  while (end < lines.length && QUOTE_LINE.test(lines[end])) end++;
  // A quote is its own paragraph: text that merely starts with ">" is not one.
  if (end === 0 || (end < lines.length && lines[end] !== "")) {
    return { quote: null, text: question };
  }
  const quoted = lines.slice(0, end).map((line) => line.slice(2));
  const source = quoted.length > 1 ? SOURCE_LINE.exec(quoted[quoted.length - 1])?.[1] : null;
  if (source) quoted.pop();
  // The locator follows the file name's last ", "; a file name may hold commas too.
  const comma = source ? source.indexOf(", ") : -1;
  let fileName = source ?? null;
  let locator: string | null = null;
  let fileId: string | undefined;
  for (let at = comma; source && at !== -1; at = source.indexOf(", ", at + 1)) {
    const suffix = source.slice(at + 2);
    const identity = FILE_LOCATOR.exec(suffix);
    if (identity && FILE_ID.test(identity[1]) && (!identity[2] || isLocator(identity[2]))) {
      fileName = source.slice(0, at);
      fileId = identity[1].toLowerCase();
      locator = identity[2] || null;
      break;
    }
    if (isLocator(suffix)) {
      fileName = source.slice(0, at);
      locator = source.slice(at + 2);
      break;
    }
  }
  return {
    quote: { text: quoted.join("\n"), fileName, locator, ...(fileId ? { fileId } : {}) },
    text: lines.slice(end + 1).join("\n")
  };
}

/** Never substitute a same-named revision for an exact file reference. */
export function quotedFileMatches(
  quote: QuestionQuote,
  file: { id: string; name: string }
): boolean {
  return quote.fileId ? file.id.toLowerCase() === quote.fileId : file.name === quote.fileName;
}
