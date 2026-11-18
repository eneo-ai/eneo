import { useEffect, useRef, type RefObject } from "react";

/**
 * Keeps focus on the same resource when `layout` swaps the markup inside
 * `box` (a phone turned across 768 px replaces rows with cards or a table,
 * and an open menu or dialog with them): the focus the old layout had goes to
 * the same resource's link in the new one (WCAG 2.4.3), not to the page.
 * Each item is a list item or table row with one `a[href]` naming it; focus
 * is tracked with focusin, which removing an element never fires.
 */
export function useFocusAcrossLayouts(box: RefObject<HTMLElement | null>, layout: unknown) {
  // The link of the resource that has the focus, null while it is elsewhere.
  const focused = useRef<string | null>(null);
  useEffect(() => {
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target as Element;
      focused.current = box.current?.contains(target)
        ? (target.closest("li, tr")?.querySelector("a[href]")?.getAttribute("href") ?? "")
        : null;
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [box]);
  useEffect(() => {
    const href = focused.current;
    if (href === null || document.activeElement !== document.body) return;
    const links = [...(box.current?.querySelectorAll<HTMLElement>("a[href]") ?? [])];
    (links.find((link) => link.getAttribute("href") === href) ?? links[0])?.focus();
  }, [box, layout]);
}
