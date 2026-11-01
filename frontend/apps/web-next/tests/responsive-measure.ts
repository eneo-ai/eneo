import type { Page } from "@playwright/test";

/**
 * What a phone user would trip over on the screen that is open, measured in the
 * page itself. Names are normalised (digits and case dropped, cut at a comma, 28
 * characters; a link by its path with ids dropped) so a test's unique names, a
 * loading state and whatever data the stack holds do not make a violation look
 * new on every run.
 */
export type Violation = {
  kind: "small" | "outside" | "overlap" | "clipped" | "clippedY" | "zoom" | "hint";
  key: string;
};

export type PageMeasure = {
  /** Page and panel scroll sideways by this many px (0 = fine). */
  overflowDoc: number;
  overflowPanel: number;
  violations: Violation[];
};

/** Targets under this many px, measured on a touch pointer (the Eneo standard). */
export const MIN_TARGET = 44;

/**
 * `vertical` also looks for text cut off at the bottom (kind `clippedY`: an
 * `overflow-y: hidden` box whose content is taller than it). It is off for the
 * contract, which only has the screen as it opens; the text-size specs turn it
 * on and compare with the screen before the text grew.
 */
export function measure(page: Page, { vertical = false } = {}): Promise<PageMeasure> {
  return page.evaluate(
    ([minTarget, withVertical]) => {
      const width = innerWidth;
      const shown = (element: Element) => {
        // What a closed <details> holds is not on screen, whatever box it kept from before.
        const closed = element.closest("details:not([open])");
        if (closed && !element.closest("summary")) return false;
        const box = element.getBoundingClientRect();
        if (!box.width || !box.height) return false;
        const style = getComputedStyle(element);
        return style.visibility !== "hidden" && style.display !== "none" && style.opacity !== "0";
      };
      // A link is named by where it goes, ids dropped: a list's rows carry the names of
      // whatever the stack holds, so naming them by text makes the baseline depend on data.
      const linkName = (link: HTMLAnchorElement) => {
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin) return `a:${url.host}`;
        const id =
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^[0-9a-f]{20,}$|^[0-9]{4,}$/i;
        const path = url.pathname
          .split("/")
          .map((segment) => (id.test(segment) ? "$" : segment))
          .join("/");
        return `a:${path}${url.hash ? "#" : ""}`;
      };
      const name = (element: Element) => {
        if (element instanceof HTMLAnchorElement && element.getAttribute("href")?.startsWith("/"))
          return linkName(element);
        const role = element.getAttribute("role");
        // What follows a comma or a dot is state (loading, a count, a status), which
        // differs from one run to the next; the leading label names the control.
        const text = (element.getAttribute("aria-label") ?? element.textContent ?? "")
          .split(/[,·]/)[0]!
          .replace(/[0-9]+/g, "")
          .replace(/\s+/g, " ")
          .trim()
          .toLowerCase()
          .slice(0, 28);
        return `${element.tagName.toLowerCase()}${role ? `[${role}]` : ""}:${text}`;
      };
      const controls =
        "a[href], button, [role=button], [role=tab], [role=menuitem], [role=option], [role=switch], [role=checkbox], [role=radio], input:not([type=hidden]), select, textarea, summary";
      const violations: Violation[] = [];
      const targets: { element: Element; box: DOMRect }[] = [];
      // A text field is tapped anywhere in its frame, not only on the <input>
      // inside it: Astryx draws the 44 px frame around a 23 px input. A number
      // field's frame focuses its spinbutton the same way (useInputContainer).
      // The same goes for a selector: its frame opens it wherever a finger lands,
      // and the <button> inside is only the 16 px label and chevron. A typeahead's
      // frame focuses its combobox <input> on click (Astryx handleWrapperClick).
      // The <label> a tap on which checks this input (not one around several controls, or one
      // whose `for` points at another).
      const labelOf = (input: Element) => {
        const label = input.closest("label");
        return label && label.control === input ? label : input;
      };
      const hitArea = (element: Element) =>
        element.matches("input:not([type=checkbox], [type=radio], [type=file]), textarea")
          ? (element.closest(
              "label, [class*='text-input'], [class*='textarea'], .astryx-number-input, .astryx-typeahead"
            ) ?? element)
          : element.matches("input[type=checkbox], input[type=radio]")
            ? // A native checkbox or radio inside a <label> is checked by a tap anywhere on that
              // label (the browser forwards it), so the label is its target: the choice cards on
              // /admin/storage are whole-card labels around a 13 px radio. A label too small to
              // tap is still reported, by its own box.
              labelOf(element)
            : element.matches("button[aria-haspopup]")
              ? (element.closest(".astryx-selector") ?? element)
              : element;
      // A control under something else at its centre cannot be tapped: a list
      // clipped by its scroll area, a menu under another. Below the fold or
      // beside the screen it is reachable by scrolling, so it still counts.
      const covered = (element: Element, box: DOMRect) => {
        const x = box.left + box.width / 2;
        const y = box.top + box.height / 2;
        if (x < 0 || x >= innerWidth || y < 0 || y >= innerHeight) return false;
        const top = document.elementFromPoint(x, y);
        return !top || !(element.contains(top) || top.contains(element));
      };
      // A control beside the screen in a strip or table that scrolls sideways
      // (Astryx TabList fades its edges, snaps and keeps the current tab in view;
      // the legacy tab list shows the next tab cut off; a wide table's scroll
      // region takes the keyboard) is a swipe away, like one below the fold. It is
      // outside only when its nearest sideways scroller cannot show it: the scroller
      // runs past the screen itself, is narrower than the control, or holds it before
      // its scroll origin, where a centred strip pushes its overflow and no scrolling
      // reaches.
      // Left-to-right only: the app ships no right-to-left locale.
      const scrollsIntoView = (element: Element, box: DOMRect) => {
        for (let node = element.parentElement; node; node = node.parentElement) {
          if (
            !/^(auto|scroll|overlay)$/.test(getComputedStyle(node).overflowX) ||
            node.scrollWidth <= node.clientWidth
          )
            continue;
          const port = node.getBoundingClientRect();
          const start = port.left + node.clientLeft - node.scrollLeft;
          return (
            port.left >= -1 &&
            port.right <= width + 1 &&
            box.width <= node.clientWidth + 1 &&
            box.left >= start - 1 &&
            box.right <= start + node.scrollWidth + 1
          );
        }
        return false;
      };
      for (const element of document.querySelectorAll(controls)) {
        if (!shown(element) || element.closest("[inert], [aria-hidden=true]")) continue;
        const area = hitArea(element);
        const box = area.getBoundingClientRect();
        // Skip link: visually hidden until focused.
        if (box.width <= 1 && box.height <= 1) continue;
        if (covered(area, box)) continue;
        // A link inside running text is sized by its line, not by a finger.
        const inline =
          element.tagName === "A" &&
          getComputedStyle(element).display === "inline" &&
          !!element.closest("p, li, span, td");
        if ((box.right > width + 1 || box.left < -1) && !scrollsIntoView(element, box))
          violations.push({ kind: "outside", key: name(element) });
        // A list row's link is stretched over the whole row by its ::after
        // (globals.css 12b), so the row is what a finger lands on.
        const tapBox = element.matches(".astryx-item > a")
          ? (element.closest(".astryx-item")?.getBoundingClientRect() ?? box)
          : box;
        // A control that takes pointer input on a larger, invisible area of its own
        // (a switch's or checkbox's ::after) is as big as that area.
        let tapWidth = tapBox.width;
        let tapHeight = tapBox.height;
        for (const pseudo of ["::before", "::after"]) {
          const style = getComputedStyle(element, pseudo);
          if (
            style.content !== "none" &&
            style.position === "absolute" &&
            style.pointerEvents !== "none"
          ) {
            tapWidth = Math.max(tapWidth, parseFloat(style.width) || 0);
            tapHeight = Math.max(tapHeight, parseFloat(style.height) || 0);
          }
        }
        if (!inline && (tapWidth < minTarget - 0.5 || tapHeight < minTarget - 0.5))
          violations.push({ kind: "small", key: name(element) });
        // iPhone Safari zooms into a field under 16 px when it takes focus, and the
        // page stays zoomed. (iPadOS does not, so the check is for phone widths.)
        if (
          width < 768 &&
          element.matches(
            "input:not([type=checkbox], [type=radio], [type=file], [type=range], [type=color], [type=button], [type=submit]), textarea, select"
          ) &&
          parseFloat(getComputedStyle(element).fontSize) < 16
        )
          violations.push({ kind: "zoom", key: name(element) });
        targets.push({ element: area, box });
      }
      // A key hint (⌘ ↵, ⌘K) points at keys a touch screen does not have.
      for (const key of document.querySelectorAll("kbd")) {
        if (shown(key))
          violations.push({ kind: "hint", key: `kbd:${(key.textContent ?? "").trim()}` });
      }
      for (let i = 0; i < targets.length; i++) {
        for (let j = i + 1; j < targets.length; j++) {
          const a = targets[i]!;
          const b = targets[j]!;
          if (a.element.contains(b.element) || b.element.contains(a.element)) continue;
          // A docked bar is fixed over the page's end, which scrolls clear of it; a
          // pinned table column covers what scrolls under it.
          if (
            a.element.closest("[data-docked-actions]") !==
            b.element.closest("[data-docked-actions]")
          )
            continue;
          const pinned = (element: Element) => {
            const cell = element.closest("td, th");
            return cell !== null && getComputedStyle(cell).position === "sticky";
          };
          if (pinned(a.element) !== pinned(b.element)) continue;
          const w = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
          const h = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
          if (w > 4 && h > 4)
            violations.push({ kind: "overlap", key: `${name(a.element)} x ${name(b.element)}` });
        }
      }
      const panel = document.getElementById("main-content") ?? document.body;
      for (const element of panel.querySelectorAll("*")) {
        const style = getComputedStyle(element);
        const text = (element.textContent ?? "").trim();
        if (!text || !shown(element)) continue;
        // Screen-reader text is clipped to a pixel on purpose.
        const box = element.getBoundingClientRect();
        if (box.width <= 1 && box.height <= 1) continue;
        const sideways =
          (style.overflowX === "hidden" || style.overflowX === "clip") &&
          style.textOverflow !== "ellipsis" &&
          element.scrollWidth > element.clientWidth + 2;
        if (sideways) violations.push({ kind: "clipped", key: `x ${name(element)}` });
        // A line clamp cuts on purpose.
        const cutBelow =
          withVertical &&
          (style.overflowY === "hidden" || style.overflowY === "clip") &&
          style.getPropertyValue("-webkit-line-clamp") === "none" &&
          element.scrollHeight > element.clientHeight + 2;
        if (cutBelow) violations.push({ kind: "clippedY", key: `y ${name(element)}` });
      }
      const doc = document.documentElement;
      return {
        overflowDoc: doc.scrollWidth - doc.clientWidth,
        overflowPanel: panel.scrollWidth - panel.clientWidth,
        violations
      };
    },
    [MIN_TARGET, vertical] as const
  );
}
