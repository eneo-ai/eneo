import type { Node } from "@tiptap/pm/model";
import { type CellSelection, TableMap } from "@tiptap/pm/tables";
import {
  MAX_MATCHES,
  occurrenceIndex,
  occurrenceLocator,
  parseTableCellsLocator,
  stripForMatch,
  tableCellsLocator
} from "../passageLocator";

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

/** The document's tables in order, each with the position its rows start at. */
function tables(doc: Node): { node: Node; start: number }[] {
  const found: { node: Node; start: number }[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "table") return true;
    found.push({ node, start: pos + 1 });
    return false;
  });
  return found;
}

const cellText = (cell: Node | null) => (cell?.textContent ?? "").replace(/\s+/g, " ").trim();

/**
 * A rectangle of selected cells as a quote: one line per row with the cells
 * between bars, as a Markdown table reads, and a locator naming the cells so
 * they can be pointed out again.
 */
export function cellSelectionQuote(
  doc: Node,
  selection: CellSelection
): { text: string; locator: string } {
  const start = selection.$anchorCell.start(-1);
  const table = selection.$anchorCell.node(-1);
  const map = TableMap.get(table);
  const rect = map.rectBetween(selection.$anchorCell.pos - start, selection.$headCell.pos - start);
  const line = (row: number) => {
    const cells = map.cellsInRect({ ...rect, top: row, bottom: row + 1 });
    return `| ${cells.map((pos) => cellText(table.nodeAt(pos))).join(" | ")} |`;
  };
  // The table's header row names the columns, so the quote reads as a table
  // of its own even when the header was not selected.
  const lines = rect.top > 0 ? [line(0)] : [];
  for (let row = rect.top; row < rect.bottom; row++) lines.push(line(row));
  lines.splice(1, 0, `|${" --- |".repeat(rect.right - rect.left)}`);
  const index = tables(doc).findIndex((candidate) => candidate.start === start) + 1;
  return {
    text: lines.join("\n"),
    locator: tableCellsLocator(index, [rect.top + 1, rect.bottom], [rect.left + 1, rect.right])
  };
}

/** The content of each cell a table locator points at; null for any other locator. */
function findTableCellSpans(doc: Node, locator: string | null): Span[] | null {
  const parsed = parseTableCellsLocator(locator);
  if (!parsed) return null;
  const table = tables(doc)[parsed.table - 1];
  if (!table) return [];
  const map = TableMap.get(table.node);
  const rect = {
    top: Math.max(0, parsed.rows[0] - 1),
    bottom: Math.min(map.height, parsed.rows[1]),
    left: Math.max(0, parsed.columns[0] - 1),
    right: Math.min(map.width, parsed.columns[1])
  };
  if (rect.top >= rect.bottom || rect.left >= rect.right) return [];
  return map.cellsInRect(rect).flatMap((pos) => {
    const cell = table.node.nodeAt(pos);
    return cell ? [{ from: table.start + pos + 1, to: table.start + pos + cell.nodeSize - 1 }] : [];
  });
}

/**
 * The place of a quoted passage in the document: the cells a table locator
 * names, the one occurrence an occurrence locator points at, else every
 * occurrence, since the text alone cannot tell them apart.
 */
export function findPassageSpans(doc: Node, passage: string, locator: string | null): Span[] {
  const cells = findTableCellSpans(doc, locator);
  if (cells) return cells;
  const occurrences = findOccurrences(doc, passage);
  const index = occurrenceIndex(locator);
  const match = index === null ? undefined : occurrences[index - 1];
  return match ? [match] : occurrences;
}
