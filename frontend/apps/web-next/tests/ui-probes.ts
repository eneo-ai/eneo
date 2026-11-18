import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { contrastRatio, over, parseColor, type Rgba } from "../src/theme/contrast-math";
import { assertDocumented } from "../src/test/wcag";
import { controlName } from "./responsive-measure";

/*
 * UI probes: checks that run on a screen a walk has already opened, one call each, so a new
 * check costs milliseconds and no page visit. A probe is a pure function of the page and the
 * cell it is measured in, and returns problems keyed so the key stays the same from run to
 * run (no ratio, no data); the detail carries the numbers. A review problem is something the
 * probe could not judge (text over an image): it is reported, never failed, because a wrong
 * failure costs more than a miss.
 *
 *   tests/contrast-probe.ts   text 4.5:1 (3:1 large), field boundaries and icon-only controls
 *                             3:1, at rest and with hover, pressed and keyboard focus forced
 *   tests/selected-probe.ts   a selected plate raised in dark mode; colour-only cues for review
 *   tests/left-edge-probe.ts  heading and first row on the shared column's left edge
 *
 * Each probe holds its known findings in tests/<probe>-probe.baseline.json (budget 0 in
 * src/test/ui-probes-baseline.test.ts); PROBES_UPDATE=1 rewrites the entries of the scans a
 * run makes. tests/ui-probes.spec.ts proves each probe on hand-made pages.
 */

export type Cell = {
  viewport: { width: number; height: number };
  theme: "light" | "dark";
  /** A touch screen: no hover to force. */
  touch: boolean;
};
export type Problem = { key: string; detail: string; review?: boolean };
export type Probe = (page: Page, cell: Cell) => Promise<Problem[]>;

/**
 * Development-only tooling, absent from the production build CI scans: the Vite error overlay
 * and the TanStack Query devtools button. tests/a11y.spec.ts excludes the same.
 */
export const DEV_ONLY = ["vite-error-overlay", ".tsqd-parent-container"];

/** probe key (`contrast text p:…`) → why it cannot be fixed, with an issue link. Fix instead. */
const EXCEPTIONS: Record<string, string> = {};
assertDocumented(EXCEPTIONS, (key) => `Excusing the probe finding "${key}"`);

/**
 * What the probes read in the page: computed colours as `rgba()`, a node's own paint, and the
 * paint under a point (an ancestor walk, cross-checked with elementsFromPoint). It runs in the
 * page, so it uses nothing from this file; `name` is controlName, passed in as source.
 */
export function pageKit(skip: string[], name: typeof controlName) {
  const styles = new Map<Element, CSSStyleDeclaration>();
  const style = (el: Element) => {
    let found = styles.get(el);
    if (!found) styles.set(el, (found = getComputedStyle(el)));
    return found;
  };
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true })!;
  const seen = new Map<string, string>();
  // Computed colours are rgb() already; oklab(), color() and color-mix() go through a canvas.
  const rgba = (value: string) => {
    if (/^rgba?\(/.test(value)) return value;
    let colour = seen.get(value);
    if (!colour) {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = "rgba(0, 0, 0, 0)";
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
      seen.set(value, (colour = `rgba(${r}, ${g}, ${b}, ${a! / 255})`));
    }
    return colour;
  };
  const channels = (colour: string) =>
    colour
      .slice(colour.indexOf("(") + 1, -1)
      .split(/[\s,/]+/)
      .filter(Boolean)
      .map(Number);
  const alpha = (colour: string) => channels(colour)[3] ?? 1;
  const fade = (colour: string, by: number) => {
    const [r, g, b, a = 1] = channels(colour);
    return `rgba(${r}, ${g}, ${b}, ${a * by})`;
  };
  const splitTop = (value: string) => {
    const parts: string[] = [];
    let depth = 0;
    let part = "";
    for (const char of value) {
      if (char === "(") depth += 1;
      if (char === ")") depth -= 1;
      if (char === "," && depth === 0) {
        parts.push(part.trim());
        part = "";
      } else part += char;
    }
    return [...parts, part.trim()];
  };
  // `linear-gradient(c, c)`: one colour, how Astryx and the legacy buttons paint hover and pressed.
  const flat = (image: string) => {
    const inner = /^linear-gradient\(([\s\S]*)\)$/.exec(image)?.[1];
    if (!inner) return null;
    const stops = splitTop(inner)
      .filter((part) => !/^to\s|^-?[\d.]+(deg|turn|rad|grad)$/.test(part))
      .map((stop) => rgba(stop.replace(/(\s+-?[\d.]+(%|px))+$/, "")));
    return stops.every((stop) => stop === stops[0]) ? stops[0]! : null;
  };
  /** Pushes a node's own background, bottom to top; returns why it cannot be judged, if so. */
  const ownLayers = (node: Element, opacity: number, out: string[]) => {
    const s = style(node);
    let review: string | undefined;
    const background = rgba(s.backgroundColor);
    if (alpha(background) > 0) out.push(fade(background, opacity));
    if (s.backgroundImage !== "none") {
      for (const image of splitTop(s.backgroundImage).reverse()) {
        const colour = flat(image);
        if (colour) out.push(fade(colour, opacity));
        else review = image.startsWith("url(") ? "image" : "gradient";
      }
    }
    return review;
  };
  const paints = (node: Element) =>
    alpha(rgba(style(node).backgroundColor)) > 0 || style(node).backgroundImage !== "none";
  /** Border and 1 px ring colours, where the node draws them. */
  const edges = (node: Element) => {
    const s = style(node);
    const out: string[] = [];
    for (const side of ["Top", "Right", "Bottom", "Left"] as const) {
      if (parseFloat(s[`border${side}Width`]) >= 1 && !/none|hidden/.test(s[`border${side}Style`]))
        out.push(rgba(s[`border${side}Color`]));
    }
    for (const shadow of s.boxShadow === "none" ? [] : splitTop(s.boxShadow)) {
      const colour = /^\w+\([^)]*\)/.exec(shadow)?.[0];
      const [, , blur = 0, spread = 0] = (shadow.match(/-?[\d.]+px/g) ?? []).map(parseFloat);
      if (colour && spread >= 1 && blur <= 1) out.push(rgba(colour));
    }
    return out;
  };
  const visible = (el: Element) => {
    if (el.closest("details:not([open])") && !el.closest("summary")) return false;
    if (el.closest(["[inert]", ...skip].join(","))) return false;
    const box = el.getBoundingClientRect();
    // Under 2 px: screen-reader text, clipped to a pixel on purpose.
    if (box.width <= 1 || box.height <= 1) return false;
    return style(el).visibility !== "hidden" && style(el).display !== "none";
  };
  // Text of an inactive control needs no contrast (1.4.3), its label's text included.
  const disabled = (el: Element) =>
    !!el.closest(":disabled, [aria-disabled=true], [data-disabled]:not([data-disabled=false])") ||
    !!el.closest("label")?.control?.matches(":disabled, [aria-disabled=true]");
  /** Visible text inside, not counting screen-reader text. */
  const hasText = (el: Element) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (node.textContent?.trim() && parent && !parent.closest("svg") && visible(parent))
        return true;
    }
    return false;
  };
  // What is under everything: the Canvas colour of the page's colour scheme.
  const base = (() => {
    const probe = document.createElement("div");
    probe.style.background = "Canvas";
    document.documentElement.append(probe);
    const colour = rgba(getComputedStyle(probe).backgroundColor);
    probe.remove();
    return colour;
  })();
  // A positioned child that paints a surface (a hover plate, a backdrop) is under its siblings'
  // text but not their ancestor: the walk adds it where it covers the point.
  const backdrops = new Map<Element, Element[]>();
  const backdropsOf = (node: Element) => {
    let found = backdrops.get(node);
    if (!found) {
      found = [...node.children].filter(
        (child) =>
          /^(absolute|fixed)$/.test(style(child).position) &&
          paints(child) &&
          Number(style(child).opacity) > 0 &&
          style(child).visibility !== "hidden"
      );
      backdrops.set(node, found);
    }
    return found;
  };
  const plates = new Map<Element, boolean>();
  const pseudoPlate = (node: Element) => {
    if (!plates.has(node)) {
      plates.set(
        node,
        ["::before", "::after"].some((pseudo) => {
          const s = getComputedStyle(node, pseudo);
          return (
            s.content !== "none" &&
            s.position === "absolute" &&
            (alpha(rgba(s.backgroundColor)) > 0 || s.backgroundImage !== "none") &&
            parseFloat(s.width) > 4 &&
            parseFloat(s.height) > 4
          );
        })
      );
    }
    return plates.get(node)!;
  };
  /**
   * The paint under point (x, y) of `el`, bottom to top. `opacity` is what its ancestors' opacity
   * multiplies the text's alpha by: exact while the translucent group paints nothing itself, but
   * CSS fades a group as one picture, so paint inside one is left for review. `covered`:
   * something else is painted over the point.
   */
  const paint = (el: Element, x: number, y: number) => {
    const chain: Element[] = [];
    for (let node: Element | null = el; node; node = node.parentElement) chain.unshift(node);
    const layers = [base];
    const used = new Set<Element>();
    let opacity = 1;
    let review: string | undefined;
    for (const [index, node] of chain.entries()) {
      const s = style(node);
      opacity *= Number(s.opacity);
      const below = layers.length;
      if (s.filter !== "none" || s.backdropFilter !== "none" || s.mixBlendMode !== "normal")
        review ??= "filter";
      review = ownLayers(node, opacity, layers) ?? review;
      if (pseudoPlate(node)) review ??= "pseudo";
      if (index === chain.length - 1) {
        // The measured element's own background is faded with its text as one picture too.
        if (opacity < 1 && layers.length > below) review ??= "opacity";
        continue;
      }
      for (const extra of backdropsOf(node)) {
        const box = extra.getBoundingClientRect();
        if (chain.includes(extra) || x < box.left || x > box.right || y < box.top || y > box.bottom)
          continue;
        used.add(extra);
        review = ownLayers(extra, opacity * Number(style(extra).opacity), layers) ?? review;
      }
      if (opacity < 1 && layers.length > below) review ??= "opacity";
    }
    if (x >= 0 && y >= 0 && x < innerWidth && y < innerHeight) {
      const hits = document.elementsFromPoint(x, y);
      const mine = hits.findIndex((hit) => hit === el || el.contains(hit) || hit.contains(el));
      // Not at its own point: clipped by a scroller, or under something that takes the pointer.
      if (mine < 0 && style(el).pointerEvents !== "none") return { layers, opacity, covered: true };
      // A translucent backdrop the walk added may sit over the text in hit order: a tint over
      // text and background alike, not a cover.
      const opaque = (hit: Element) =>
        alpha(rgba(style(hit).backgroundColor)) >= 1 && Number(style(hit).opacity) >= 1;
      const over = hits.slice(0, Math.max(mine, 0));
      if (over.some((hit) => paints(hit) && (!used.has(hit) || opaque(hit))))
        return { layers, opacity, covered: true };
      const unrelated = (hit: Element) => !hit.contains(el) && !el.contains(hit) && !used.has(hit);
      if (mine >= 0 && hits.slice(mine).some((hit) => unrelated(hit) && paints(hit)))
        review ??= "overlap";
    }
    return { layers, opacity, review, covered: false };
  };
  /** Ends running transitions, so a forced state is read as it ends, not as it starts. */
  const settle = () => {
    for (const animation of document.getAnimations()) {
      try {
        animation.finish();
      } catch {
        // An infinite animation (a spinner) cannot finish; it paints no text.
      }
    }
  };
  return {
    style,
    rgba,
    alpha,
    fade,
    ownLayers,
    edges,
    visible,
    disabled,
    hasText,
    name,
    paint,
    settle
  };
}

export type Kit = ReturnType<typeof pageKit>;

/** Runs `collect` in the page with the kit, as one evaluate. */
export function inPage<A, R>(page: Page, collect: (kit: Kit, arg: A) => R, arg: A): Promise<R> {
  return page.evaluate(
    `(${collect})((${pageKit})(${JSON.stringify(DEV_ONLY)}, ${controlName}), ${JSON.stringify(arg)})`
  ) as Promise<R>;
}

/** Layers bottom to top (the first opaque) as one colour. */
export const fold = (layers: string[]): Rgba =>
  layers.map(parseColor).reduce((below, layer) => over(layer, below));

/** The ratio as axe reports it: floored to two decimals. */
export const ratio = (foreground: Rgba, background: Rgba) =>
  Math.floor(contrastRatio(foreground, background) * 100) / 100;

const update = process.env.PROBES_UPDATE === "1";

/**
 * The baseline's verdict on one scan (`<variant>|<screen>`) of one probe: a finding the
 * baseline does not list fails, and so does an entry that no longer occurs. Review problems
 * are not judged here.
 */
export function probeBaseline(probe: string, scan: string, problems: Problem[]): string[] {
  const file = path.resolve(process.cwd(), `tests/${probe}-probe.baseline.json`);
  const found = problems.filter(
    (problem) => !problem.review && !(`${probe} ${problem.key}` in EXCEPTIONS)
  );
  const baseline: Record<string, string[]> = JSON.parse(fs.readFileSync(file, "utf8"));
  if (update) {
    // workers: 1 (playwright.config.ts), so read-merge-write cannot interleave.
    if (found.length) baseline[scan] = [...new Set(found.map(({ key }) => key))].sort();
    else delete baseline[scan];
    const sorted = Object.fromEntries(
      Object.entries(baseline).sort(([a], [b]) => a.localeCompare(b))
    );
    fs.writeFileSync(file, JSON.stringify(sorted, null, 1) + "\n");
    return [];
  }
  const known = new Set(baseline[scan] ?? []);
  return [
    ...found
      .filter(({ key }) => !known.has(key))
      .map(({ key, detail }) => `${scan}: ${probe} ${key}: ${detail}`),
    ...[...known]
      .filter((key) => !found.some((problem) => problem.key === key))
      .map((key) => `${scan}: ${probe} "${key}" no longer occurs: remove it from the baseline`)
  ];
}
