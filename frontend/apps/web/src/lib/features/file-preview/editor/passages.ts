import type { Node } from "@tiptap/pm/model";
import { MAX_MATCHES, occurrenceIndex, occurrenceLocator, stripForMatch } from "../passageLocator";

/** A stretch of a ProseMirror document, as positions in it. */
export type Span = { from: number; to: number };

/**
 * The document's text with whitespace removed, and for each of its characters
 * the position it stands at. A quote is matched against this: a selection
 * reports line breaks between blocks that the text nodes do not hold.
 */
export function documentText(doc: Node): { text: string; positions: number[] } {
  let text = "";
  const positions: number[] = [];
  doc.descendants((node, pos) => {
    if (!node.isText) return true;
    const value = node.text ?? "";
    for (let offset = 0; offset < value.length; offset++) {
      if (/\s/.test(value[offset])) continue;
      text += value[offset];
      positions.push(pos + offset);
    }
    return false;
  });
  return { text, positions };
}

/** Every place where `passage` stands in the document, in document order. */
export function findOccurrences(doc: Node, passage: string): Span[] {
  const needle = stripForMatch(passage);
  if (!needle) return [];
  const { text, positions } = documentText(doc);
  const spans: Span[] = [];
  for (
    let at = text.indexOf(needle);
    at !== -1 && spans.length < MAX_MATCHES;
    at = text.indexOf(needle, at + needle.length)
  ) {
    spans.push({ from: positions[at], to: positions[at + needle.length - 1] + 1 });
  }
  return spans;
}

/** The selected text as a quote reads it: blocks on lines of their own. */
export const selectedText = (doc: Node, from: number, to: number) =>
  doc.textBetween(from, to, "\n");

/**
 * Where the selection stands, in words: which occurrence it is when its text
 * appears more than once. Null when the text alone identifies it.
 */
export function locateSelection(doc: Node, from: number, to: number): string | null {
  const occurrences = findOccurrences(doc, selectedText(doc, from, to));
  if (occurrences.length < 2 || occurrences.length === MAX_MATCHES) return null;
  // The selection may start in whitespace just before the text that matched.
  const index = occurrences.findIndex((occurrence) => occurrence.to >= to);
  return index === -1 ? null : occurrenceLocator(index + 1, occurrences.length);
}

/**
 * The place of a quoted passage in the document: the one occurrence its
 * locator points at, else every occurrence, since the text alone cannot tell
 * them apart.
 */
export function findPassageSpans(doc: Node, passage: string, locator: string | null): Span[] {
  const occurrences = findOccurrences(doc, passage);
  const index = occurrenceIndex(locator);
  const match = index === null ? undefined : occurrences[index - 1];
  return match ? [match] : occurrences;
}
