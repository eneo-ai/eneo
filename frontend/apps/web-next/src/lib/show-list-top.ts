/**
 * After turning a page: the Previous/Next buttons are at the end of the list, so on a
 * touch screen the new page's first rows are a long scroll above the thumb. Bring the
 * list's top back into view. A keyboard keeps its place: focus stays on the button
 * that was pressed, and jumping away from it would lose it.
 */
export function showListTop(list: Element | null): void {
  if (list && window.matchMedia("(pointer: coarse)").matches)
    list.scrollIntoView({ block: "start" });
}
