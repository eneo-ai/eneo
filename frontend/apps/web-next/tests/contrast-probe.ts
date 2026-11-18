import { parseColor } from "../src/theme/contrast-math";
import { fold, inPage, ratio, type Kit, type Probe, type Problem } from "./ui-probes";

/*
 * Contrast where axe cannot judge it (tests/ui-probes.ts). axe calls text over a gradient
 * "incomplete", and Astryx and the legacy buttons paint hover and pressed as
 * `linear-gradient(c, c)`; it has no rule for 1.4.11 at all. This probe composites the paint
 * under each piece of text itself (a one-colour gradient is a flat overlay; an image, a real
 * gradient, a filter, a painted pseudo-element or paint inside a translucent group is left for
 * review) and holds:
 * - text and placeholders to 4.5:1, large text (24 px, or 18.66 px bold) to 3:1 (1.4.3);
 * - a field's, checkbox's or switch's boundary, and an icon-only control's icon, to 3:1 (1.4.11).
 * A selected option against its track is tests/selected-probe.ts. Disabled controls are exempt.
 * In Chromium it then forces :hover (not on a touch screen, where nothing hovers), :active and
 * :focus-visible on one control of each kind and measures them again; other engines get the
 * resting pass only.
 */

type Item = {
  kind: "text" | "placeholder" | "boundary" | "icon";
  sig: string;
  /** Candidate colours; one at its minimum passes (a boundary: any edge, or the fill). */
  fg: string[];
  layers: string[];
  large?: boolean;
  review?: string;
};

const NEEDS = { text: 4.5, placeholder: 4.5, boundary: 3, icon: 3 };

/** In the page: everything the verdict needs, inside `scope` (the whole page by default). */
function collect(kit: Kit, { state, scope }: { state?: string; scope?: string }): Item[] {
  if (state) kit.settle();
  const items: Item[] = [];
  const add = (item: Omit<Item, "layers">, at: Element, box: DOMRect) => {
    const paint = kit.paint(at, box.left + box.width / 2, box.top + box.height / 2);
    if (paint.covered || paint.opacity < 0.05) return;
    const fg = item.fg.map((colour) => kit.fade(colour, paint.opacity));
    items.push({ ...item, fg, layers: paint.layers, review: item.review ?? paint.review });
  };
  const roots = scope ? [...document.querySelectorAll(scope)] : [document.body];
  const fields =
    "input:not([type=hidden],[type=submit],[type=button],[type=reset],[type=image],[type=range],[type=color],[type=file]), textarea, select, [role=combobox], [role=textbox], [role=switch], [role=checkbox], [role=radio]";
  const typed = "input:not([type=checkbox],[type=radio]), textarea";
  const frames = "[class*='text-input'], [class*='textarea'], .astryx-typeahead, .astryx-selector";
  // A box draws a boundary with an edge, or with a fill other than the one behind it (a
  // <textarea>'s white on a white card draws none).
  const painted = (node: Element) => {
    if (kit.edges(node).some((colour) => kit.alpha(colour) > 0)) return true;
    const fill = kit.rgba(kit.style(node).backgroundColor);
    let behind = "rgba(0, 0, 0, 0)";
    for (let up = node.parentElement; up && !kit.alpha(behind); up = up.parentElement)
      behind = kit.rgba(kit.style(up).backgroundColor);
    return kit.alpha(fill) > 0 && fill !== behind;
  };
  // A forced state's scope is the control itself, which querySelectorAll leaves out.
  const within = (root: Element, selector: string) =>
    [root, ...root.querySelectorAll(selector)].filter((el) => el.matches(selector));
  for (const root of roots) {
    const seen = new Set<Element>();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const el = node.parentElement;
      if (!el || seen.has(el) || !node.textContent?.trim()) continue;
      seen.add(el);
      if (el.closest("script, style, noscript, template, svg, textarea, select")) continue;
      if (!kit.visible(el) || kit.disabled(el)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const box = range.getClientRects()[0];
      if (!box || box.width < 1 || box.height < 1) continue;
      const s = kit.style(el);
      const size = parseFloat(s.fontSize);
      const fill = s.getPropertyValue("-webkit-text-fill-color") || s.color;
      const large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700);
      add({ kind: "text", sig: kit.name(el), fg: [kit.rgba(fill)], large }, el, box);
    }
    for (const el of within(root, fields)) {
      if (kit.disabled(el)) continue;
      // A hidden native select a custom select mirrors for its form (Radix): what it
      // stands for is the visible trigger, measured on its own.
      if (!kit.visible(el) && el.closest("[aria-hidden=true]")) continue;
      const box = el.getBoundingClientRect();
      if (el.matches(typed) && kit.visible(el)) {
        const field = el as HTMLInputElement;
        if (field.value)
          add({ kind: "text", sig: kit.name(el), fg: [kit.rgba(kit.style(el).color)] }, el, box);
        else if (field.placeholder && el.matches(":placeholder-shown")) {
          const colour = kit.rgba(getComputedStyle(el, "::placeholder").color);
          add({ kind: "placeholder", sig: kit.name(el), fg: [colour] }, el, box);
        }
      }
      // What draws the boundary: the nearest box that paints, from the field's frame (an
      // Astryx text input draws it, not its <input>) or the indicator beside a hidden native
      // checkbox. A native control the browser draws, and a radio or checkbox that is a text
      // button (a segmented control's option), draw none of their own to judge here.
      let start: Element | null | undefined = el;
      if (el.matches("input[type=checkbox], input[type=radio]")) {
        start =
          kit.visible(el) && Number(kit.style(el).opacity) > 0.05
            ? kit.style(el).appearance === "none"
              ? el
              : null
            : [...el.parentElement!.children].find((other) => other !== el && kit.visible(other));
      } else if (!el.matches("input, textarea, select, [role=textbox]") && kit.hasText(el)) {
        start = el.closest(".astryx-selector, .astryx-typeahead");
      } else {
        start = el.closest(frames) ?? el;
      }
      let frame = start;
      for (let up = 0; frame && up < 4 && !painted(frame); up += 1) frame = frame.parentElement;
      frame = frame && painted(frame) ? frame : start;
      if (!frame || !kit.visible(frame) || !frame.parentElement) continue;
      const fill = kit.rgba(kit.style(frame).backgroundColor);
      const frameBox = frame.getBoundingClientRect();
      const sig = kit.name(el);
      add(
        { kind: "boundary", sig, fg: [...kit.edges(frame), fill] },
        frame.parentElement,
        frameBox
      );
    }
    for (const el of within(root, "button, a[href], [role=button], [role=tab]")) {
      if (!kit.visible(el) || kit.disabled(el) || kit.hasText(el)) continue;
      const icon = [...el.querySelectorAll("svg, img")].find(kit.visible);
      if (!icon) continue;
      const shape =
        icon.querySelector("path, circle, rect, line, polyline, polygon, ellipse") ?? icon;
      const s = kit.style(shape);
      const colour = s.stroke !== "none" ? s.stroke : s.fill;
      const review =
        icon.tagName === "IMG" ? "image" : colour.startsWith("url(") ? "gradient" : undefined;
      const fg = review ? [] : [kit.rgba(colour)];
      add({ kind: "icon", sig: kit.name(el), fg, review }, icon, icon.getBoundingClientRect());
    }
  }
  return items;
}

/** In the page: one control of each kind (and its `group` ancestors, for group-hover) marked. */
function mark(kit: Kit, limit: number) {
  const kinds = new Set<string>();
  const signature = (el: Element) =>
    [
      el.tagName,
      el.getAttribute("role"),
      el.getAttribute("data-variant"),
      el.getAttribute("data-size"),
      el.getAttribute("data-state"),
      [...el.classList].slice(0, 2).join("."),
      el.parentElement?.tagName,
      [...(el.parentElement?.classList ?? [])].slice(0, 2).join(".")
    ].join("|");
  const controls =
    "a[href], button, [role=button], [role=tab], [role=menuitem], [role=option], [role=switch], [role=checkbox], [role=radio], input:not([type=hidden]), select, textarea, summary";
  for (const el of document.querySelectorAll(controls)) {
    if (kinds.size >= limit || !kit.visible(el) || kit.disabled(el)) continue;
    const kind = signature(el);
    if (kinds.has(kind)) continue;
    kinds.add(kind);
    el.setAttribute("data-ui-probe-state", "");
    for (let node = el.parentElement; node; node = node.parentElement) {
      if ([...node.classList].some((name) => /^group(\/|$)/.test(name)))
        node.setAttribute("data-ui-probe-group", "");
    }
  }
  return kinds.size;
}

function unmark(kit: Kit) {
  for (const el of document.querySelectorAll("[data-ui-probe-state], [data-ui-probe-group]")) {
    el.removeAttribute("data-ui-probe-state");
    el.removeAttribute("data-ui-probe-group");
  }
  kit.settle();
}

function verdict(items: Item[], state?: string): Problem[] {
  const worst = new Map<string, Problem & { ratio: number }>();
  for (const item of items) {
    const key = `${item.kind}${state ? `:${state}` : ""} ${item.sig}`;
    const fg = item.fg.map(parseColor);
    if (item.review || !fg.length || fg.every((colour) => colour.a === 0)) {
      const detail = `not judged: ${item.review ?? "transparent text"}`;
      if (!worst.has(key)) worst.set(key, { key, detail, review: true, ratio: Infinity });
      continue;
    }
    const background = fold(item.layers);
    const best = Math.max(...fg.map((colour) => ratio(colour, background)));
    const needs = item.large ? 3 : NEEDS[item.kind];
    const known = worst.get(key);
    if (best >= needs || (known && !known.review && known.ratio <= best)) continue;
    worst.set(key, { key, detail: `${best}:1, needs ${needs}:1`, ratio: best });
  }
  return [...worst.values()].map(({ key, detail, review }) => ({
    key,
    detail,
    ...(review && { review })
  }));
}

/** Controls measured per forced state on one screen; the rest of a long list looks the same. */
const STATE_LIMIT = 40;

export const contrastProbe: Probe = async (page, cell) => {
  const problems = verdict(await inPage(page, collect, {}));
  // A state is reported only where it makes a resting pass fail: the rest is already listed.
  const atRest = new Set(problems.map(({ key }) => key));
  if (page.context().browser()?.browserType().name() !== "chromium") return problems;
  if (!(await inPage(page, mark, STATE_LIMIT))) return problems;
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    const { root } = await cdp.send("DOM.getDocument", { depth: 0 });
    const find = async (selector: string) =>
      (await cdp.send("DOM.querySelectorAll", { nodeId: root.nodeId, selector })).nodeIds;
    const controls = await find("[data-ui-probe-state]");
    const groups = await find("[data-ui-probe-group]");
    const force = (nodes: number[], forcedPseudoClasses: string[]) =>
      Promise.all(
        nodes.map((nodeId) => cdp.send("CSS.forcePseudoState", { nodeId, forcedPseudoClasses }))
      );
    for (const state of cell.touch
      ? ["active", "focus-visible"]
      : ["hover", "active", "focus-visible"]) {
      // A pointer over or pressing a control is over its ancestors too; focus is the control's.
      const nodes = state === "focus-visible" ? controls : [...controls, ...groups];
      await force(nodes, [state]);
      const items = await inPage(page, collect, { state, scope: "[data-ui-probe-state]" });
      problems.push(
        ...verdict(items, state).filter(({ key }) => !atRest.has(key.replace(`:${state}`, "")))
      );
      await force(nodes, []);
    }
  } finally {
    await inPage(page, unmark, null);
    await cdp.detach();
  }
  return problems;
};
