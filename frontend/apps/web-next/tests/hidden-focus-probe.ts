import type { Page } from "@playwright/test";

/*
 * Focus not obscured (2.4.11): Tabbing through a screen, what has focus is not entirely hidden
 * by something fixed or sticky: the page bar, the docked action bar, the composer, a toast. The
 * browser scrolls a focused element into view; the page's scroll padding has to keep it clear
 * of those bars. A touch screen with a keyboard attached meets this too, so it runs at the
 * contract's phone and iPad sizes.
 */

const STOPS = 30;

/** What the first Tab stops of the screen `page` shows hide, named per stop. */
export async function hiddenFocusProbe(page: Page, pattern: string) {
  const found: string[] = [];
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
  const seen = new Set<string>();
  for (let stop = 0; stop < STOPS; stop++) {
    await page.keyboard.press("Tab");
    const hidden = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      if (!element || element === document.body) return null;
      const box = element.getBoundingClientRect();
      if (box.width < 2 || box.height < 2) return null;
      const label = (element.getAttribute("aria-label") || element.textContent || "")
        .trim()
        .replace(/[0-9]+/g, "")
        .replace(/\s+/g, " ")
        .slice(0, 28);
      const points = [
        [box.left + box.width / 2, box.top + box.height / 2],
        [box.left + 2, box.top + 2],
        [box.right - 2, box.top + 2],
        [box.left + 2, box.bottom - 2],
        [box.right - 2, box.bottom - 2]
      ].filter(([x, y]) => x! >= 0 && x! < innerWidth && y! >= 0 && y! < innerHeight);
      if (points.length === 0) return null;
      const covers = points.map(([x, y]) => {
        const top = document.elementFromPoint(x!, y!);
        // A tooltip of the stop before is still fading out when keys come fast; it
        // is transient content (1.4.13), not a bar the page keeps over the focus.
        if (top?.closest("[role=tooltip], .astryx-tooltip")) return null;
        return top && !element.contains(top) && !top.contains(element) ? top : null;
      });
      if (covers.some((top) => top === null)) return null;
      const top = covers[0]!;
      const style = getComputedStyle(
        top.closest("[data-docked-actions], header, nav, aside") ?? top
      );
      return {
        name: `${element.tagName.toLowerCase()}:${label}`,
        by: `${top.tagName.toLowerCase()}${top.className ? "." + String(top.className).split(" ")[0] : ""} (${style.position})`
      };
    });
    if (hidden && !seen.has(hidden.name)) {
      seen.add(hidden.name);
      found.push(`${pattern}: ${hidden.name} is entirely hidden by ${hidden.by}`);
    }
  }
  return found;
}
