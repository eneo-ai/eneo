import { inPage, type Kit, type Probe } from "./ui-probes";

/*
 * List and overview pages share one column (PAGE_COLUMN, src/components/composites/
 * page-frame.tsx) and one left edge (tests/ui-probes.ts). On a screen that has the column, each
 * column starts on the first one's edge, the h1's line (the h1's text, or a tile before it)
 * starts on it, and so does the first list row's content: a row's hover surface reaches into the
 * gutter, its text does not. A row inside a card follows the card's inset and is not measured.
 * A page that spans the frame (`data-space-full-bleed`) has no column to keep.
 */

type Edge = { key: string; detail: string; offset: number };

function collect(kit: Kit): Edge[] {
  const columns = [...document.querySelectorAll("main .mx-auto.max-w-6xl")].filter(
    (column) => kit.visible(column) && !column.querySelector("[data-space-full-bleed]")
  );
  if (!columns.length) return [];
  const contentLeft = (el: Element) =>
    el.getBoundingClientRect().left +
    parseFloat(kit.style(el).borderLeftWidth) +
    parseFloat(kit.style(el).paddingLeft);
  const edge = contentLeft(columns[0]!);
  const found: Edge[] = [];
  const at = (key: string, what: string, left: number) =>
    found.push({
      key,
      offset: Math.round(left - edge),
      detail: `${what} starts at ${Math.round(left)}`
    });
  columns.forEach((column, index) => at(`column ${index}`, "the column", contentLeft(column)));
  const heading = [...document.querySelectorAll("main h1")].find(kit.visible);
  const home = heading && columns.find((column) => column.contains(heading));
  if (heading && home) {
    const range = document.createRange();
    range.selectNodeContents(heading);
    const box = heading.getBoundingClientRect();
    const rects = [...range.getClientRects()];
    let left = Math.min(box.right, ...rects.map((rect) => rect.left));
    const textRight = Math.max(left, ...rects.map((rect) => rect.right));
    // A tile or icon before the heading, on its line, is where the line starts.
    for (let node: Element = heading; node !== home; node = node.parentElement!) {
      for (
        let before = node.previousElementSibling;
        before;
        before = before.previousElementSibling
      ) {
        const rect = before.getBoundingClientRect();
        if (kit.visible(before) && rect.bottom > box.top && rect.top < box.bottom)
          left = Math.min(left, rect.left);
      }
    }
    // A centred heading (an empty state, a not-found page) keeps no edge.
    const right = home.getBoundingClientRect().right;
    const centred = left - edge > 1 && Math.abs(left - edge - (right - textRight)) <= 2;
    if (!centred) at("heading h1", `h1 "${kit.name(heading).split(":")[1]}"`, left);
  }
  const boxed = (el: Element, column: Element) => {
    for (let node = el.parentElement; node && node !== column; node = node.parentElement) {
      const s = kit.style(node);
      const border =
        parseFloat(s.borderLeftWidth) >= 1 && kit.alpha(kit.rgba(s.borderLeftColor)) > 0;
      if (border || s.boxShadow !== "none" || kit.alpha(kit.rgba(s.backgroundColor)) > 0)
        return true;
    }
    return false;
  };
  for (const column of columns) {
    const row = [...column.querySelectorAll(".astryx-list .astryx-item")].find(
      (item) => kit.visible(item) && !boxed(item, column)
    );
    if (!row) continue;
    at("row li.astryx-item", `the first row ("${kit.name(row).split(":")[1]}")`, contentLeft(row));
    break;
  }
  return found;
}

export const leftEdgeProbe: Probe = async (page) =>
  (await inPage(page, collect, null))
    .filter(({ offset }) => Math.abs(offset) > 1)
    .map(({ key, detail, offset }) => ({
      key,
      detail: `${detail}, ${offset > 0 ? "+" : ""}${offset} px from the shared column's left edge`
    }));
