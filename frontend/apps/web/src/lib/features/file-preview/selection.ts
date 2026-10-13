import { parseTableLocator } from "./tableReference";

/** Selected text and where it is on screen, in the hosting page's viewport. */
export type SelectedPassage = {
  text: string;
  rect: { left: number; top: number; right: number; bottom: number };
  range: Range;
};

type WatchOptions = {
  /** Only a selection lying wholly inside this element counts. */
  within?: () => Element | null | undefined;
  /**
   * Where the document's viewport sits in the hosting page's viewport: the
   * frame's position, for a document shown in a frame.
   */
  origin?: () => { x: number; y: number };
  /** Called with the selection once it has settled, and with null when there is none. */
  report: (passage: SelectedPassage | null) => void;
};

/**
 * Follows the text selection of a document, the page's or a frame's.
 *
 * Nothing is reported while the pointer is still dragging the selection out, so
 * whatever is shown for it does not chase the pointer. A selection that moves
 * (the content scrolls) is reported again at its new place.
 */
export function watchSelection(doc: Document, { within, origin, report }: WatchOptions) {
  let dragging = false;

  const read = () => {
    const selection = doc.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return report(null);
    const container = within?.();
    if (
      within &&
      !(container?.contains(selection.anchorNode) && container.contains(selection.focusNode))
    ) {
      return report(null);
    }
    const text = selection.toString();
    const range = selection.getRangeAt(0).cloneRange();
    const box = range.getBoundingClientRect();
    if (!text.trim() || (box.width === 0 && box.height === 0)) return report(null);
    const { x, y } = origin?.() ?? { x: 0, y: 0 };
    report({
      text,
      range,
      rect: { left: box.left + x, top: box.top + y, right: box.right + x, bottom: box.bottom + y }
    });
  };

  const onSelectionChange = () => (dragging ? report(null) : read());
  const onPointerDown = () => (dragging = true);
  const onPointerUp = () => {
    dragging = false;
    // A click's own selection change (collapsing, or a double-click's word)
    // lands after the pointer is released.
    setTimeout(read);
  };
  const onScroll = () => {
    if (!dragging) read();
  };

  doc.addEventListener("selectionchange", onSelectionChange);
  doc.addEventListener("pointerdown", onPointerDown, true);
  doc.addEventListener("pointerup", onPointerUp, true);
  doc.addEventListener("pointercancel", onPointerUp, true);
  doc.addEventListener("scroll", onScroll, true);

  return {
    /** Reports the selection again, as after a layout change moved it. */
    refresh: onScroll,
    stop() {
      doc.removeEventListener("selectionchange", onSelectionChange);
      doc.removeEventListener("pointerdown", onPointerDown, true);
      doc.removeEventListener("pointerup", onPointerUp, true);
      doc.removeEventListener("pointercancel", onPointerUp, true);
      doc.removeEventListener("scroll", onScroll, true);
    }
  };
}

// Row numbers and other chrome are unselectable; a selection never holds them.
const UNSELECTABLE = ".select-none";
const MAX_MATCHES = 200;
const MAX_CELL_LENGTH = 60;
const MAX_CELLS_LENGTH = 300;
const ELEMENT_NODE = 1;

/**
 * Finds every place where `passage` (text once selected under `root`) stands
 * in the rendered content, in document order. Whitespace is ignored on both
 * sides: a selection reports line breaks and tabs between blocks and cells
 * that the text nodes do not hold.
 */
function findOccurrences(root: Element, passage: string): Range[] {
  const needle = passage.replace(/…$/, "").replace(/\s+/g, "");
  if (!needle) return [];

  const doc = root.ownerDocument;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.nodeType === ELEMENT_NODE && (node as Element).matches(UNSELECTABLE)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT
  });
  // The content with whitespace removed, and for each of its characters the
  // text node and offset it came from.
  let haystack = "";
  const nodes: Node[] = [];
  const offsets: number[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === ELEMENT_NODE) continue;
    const text = node.nodeValue ?? "";
    for (let offset = 0; offset < text.length; offset++) {
      if (/\s/.test(text[offset])) continue;
      haystack += text[offset];
      nodes.push(node);
      offsets.push(offset);
    }
  }

  const ranges: Range[] = [];
  for (
    let at = haystack.indexOf(needle);
    at !== -1 && ranges.length < MAX_MATCHES;
    at = haystack.indexOf(needle, at + needle.length)
  ) {
    const last = at + needle.length - 1;
    const range = doc.createRange();
    range.setStart(nodes[at], offsets[at]);
    range.setEnd(nodes[last], offsets[last] + 1);
    ranges.push(range);
  }
  return ranges;
}

const HIGHLIGHT_NAME = "file-preview-quote";
/** The rule that paints marked passages; `color` is any CSS colour. */
export const highlightRule = (color: string) =>
  `::highlight(${HIGHLIGHT_NAME}) { background-color: ${color}; }`;

/**
 * Marks `ranges` in their document (none clears the mark) and brings the first
 * into view. Painted with the CSS Custom Highlight API, which leaves the
 * content and the user's selection untouched; a browser without it only scrolls.
 */
export function markPassages(doc: Document, ranges: Range[]) {
  const view = doc.defaultView;
  if (!view) return;
  if ("highlights" in view.CSS) {
    if (ranges.length === 0) view.CSS.highlights.delete(HIGHLIGHT_NAME);
    else view.CSS.highlights.set(HIGHLIGHT_NAME, new view.Highlight(...ranges));
  }
  if (ranges.length > 0) reveal(ranges[0], view);
}

/** Scrolls whatever scrolls the range (a container, or a frame's document) to centre it. */
function reveal(range: Range, view: Window & typeof globalThis) {
  const box = range.getBoundingClientRect();
  const root = view.document.documentElement;
  let scroller = range.startContainer.parentElement;
  while (scroller && scroller !== root) {
    const style = view.getComputedStyle(scroller);
    const scrolls = /auto|scroll/.test(style.overflowY + style.overflowX);
    if (
      scrolls &&
      (scroller.scrollHeight > scroller.clientHeight || scroller.scrollWidth > scroller.clientWidth)
    ) {
      break;
    }
    scroller = scroller.parentElement;
  }
  if (scroller && scroller !== root) {
    const frame = scroller.getBoundingClientRect();
    const outside = box.left < frame.left || box.right > frame.right;
    scroller.scrollBy({
      top: box.top + box.height / 2 - (frame.top + frame.height / 2),
      left: outside ? box.left - frame.left - frame.width / 3 : 0
    });
  } else if (view.frameElement) {
    // Only a frame's document scrolls as a whole; the app's own page does not.
    view.scrollBy({ top: box.top + box.height / 2 - view.innerHeight / 2 });
  }
}

// A locator says which of several identical passages is meant. It is written
// in plain English because the model reads it too, as part of the quote's
// source line; these are the only shapes it takes.
const ROWS_LOCATOR =
  /^(?:sheet "(.*?)", )?rows? (\d+)(?:-\d+)? \((?:the header(?: and data rows? \d+(?:-\d+)?)?|data rows? \d+(?:-\d+)?)\)(?:, cells: .*)?$/;
const OCCURRENCE_LOCATOR = /^occurrence (\d+) of \d+$/;

/** Whether `text` is a locator, as opposed to the tail of a file name. */
export const isLocator = (text: string) =>
  !!parseTableLocator(text) || ROWS_LOCATOR.test(text) || OCCURRENCE_LOCATOR.test(text);

/** The sheet a locator points into, when it names one. */
export const locatorSheet = (locator: string | null) =>
  parseTableLocator(locator)?.sheet ?? ((locator && ROWS_LOCATOR.exec(locator)?.[1]) || null);

const elementOf = (node: Node) =>
  node.nodeType === ELEMENT_NODE ? (node as Element) : node.parentElement;

const span = (first: number, last: number) => (first === last ? `${first}` : `${first}-${last}`);
const plural = (first: number, last: number) => (first === last ? "" : "s");

/**
 * Rows of a table, said both ways a reader may count them: as numbered in the
 * preview, where the header is row 1, and as data rows below the header, which
 * is how a query over the table sees them. A single row also gives its cells,
 * so it can be found by content rather than by counting.
 */
function describeRows(firstRow: HTMLElement, lastRow: HTMLElement): string {
  const first = Number(firstRow.dataset.row);
  const last = Number(lastRow.dataset.row);
  const data =
    last === 1
      ? "the header"
      : `${first === 1 ? "the header and " : ""}data row${plural(Math.max(first, 2), last)} ${span(Math.max(first, 2) - 1, last - 1)}`;
  const rows = `row${plural(first, last)} ${span(first, last)} (${data})`;
  if (first !== last) return rows;
  const cells = [...firstRow.querySelectorAll(':scope > td, :scope > th[scope="col"]')]
    .map((cell) => (cell.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_CELL_LENGTH))
    .join(" | ")
    .slice(0, MAX_CELLS_LENGTH);
  return `${rows}, cells: ${cells}`;
}

/**
 * Where the selected `range` stands, in words: its rows in a table, or which
 * occurrence it is when its text appears more than once. Null when the text
 * alone identifies it.
 */
export function locatePassage(root: Element, range: Range, text: string): string | null {
  const firstRow = elementOf(range.startContainer)?.closest<HTMLElement>("tr[data-row]");
  const lastRow = elementOf(range.endContainer)?.closest<HTMLElement>("tr[data-row]");
  if (firstRow && lastRow) {
    const sheet = firstRow.closest<HTMLElement>("table[data-sheet]")?.dataset.sheet;
    return `${sheet ? `sheet "${sheet}", ` : ""}${describeRows(firstRow, lastRow)}`;
  }
  const occurrences = findOccurrences(root, text);
  if (occurrences.length < 2 || occurrences.length === MAX_MATCHES) return null;
  // The selection may start in whitespace just before the text that matched.
  const index = occurrences.findIndex(
    (occurrence) => occurrence.compareBoundaryPoints(Range.END_TO_END, range) >= 0
  );
  return index === -1 ? null : `occurrence ${index + 1} of ${occurrences.length}`;
}

/**
 * The place of a quoted passage in the rendered content: the one occurrence
 * its locator points at, else every occurrence, since the text alone cannot
 * tell them apart.
 */
export function findPassage(root: Element, passage: string, locator: string | null): Range[] {
  const table = parseTableLocator(locator);
  if (table) {
    const sheet = [...root.querySelectorAll<HTMLTableElement>("table[data-sheet]")].find(
      (element) => element.dataset.sheet === table.sheet
    );
    return (table.rows ?? [table.row]).flatMap((number) => {
      const row = sheet?.querySelector(`tr[data-row="${number}"]`);
      const target =
        table.column === null ? row : row?.querySelector(`td[data-column="${table.column}"]`);
      if (!target) return [];
      const range = root.ownerDocument.createRange();
      range.selectNodeContents(target);
      return [range];
    });
  }
  const occurrences = findOccurrences(root, passage);
  const rows = locator ? ROWS_LOCATOR.exec(locator) : null;
  const occurrence = locator ? OCCURRENCE_LOCATOR.exec(locator) : null;
  let match: Range | undefined;
  if (rows) {
    match = occurrences.find(
      (range) =>
        elementOf(range.startContainer)?.closest("tr[data-row]")?.getAttribute("data-row") ===
        rows[2]
    );
  } else if (occurrence) {
    match = occurrences[Number(occurrence[1]) - 1];
  }
  return match ? [match] : occurrences;
}
