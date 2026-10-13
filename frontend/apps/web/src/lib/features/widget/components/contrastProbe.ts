/* eslint-disable eneo/no-raw-color -- resolves computed colours for contrast assertions */
/**
 * Test helpers for the widget's component tests: what a rendered element
 * actually looks like, measured the way WCAG does. Browser only.
 */
import { contrastRatio } from "../contrast";

type Rgba = [number, number, number, number];

let context: CanvasRenderingContext2D | null = null;

/** Any CSS colour the browser computed (rgb, oklch, …) as sRGB bytes. */
function resolve(color: string): Rgba {
  context ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const ctx = context!;
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = "#000";
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b, a / 255];
}

const hex = ([r, g, b]: Rgba) =>
  `#${[r, g, b].map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;

function over(top: Rgba, bottom: Rgba): Rgba {
  const [r, g, b, a] = top;
  return [
    Math.round(r * a + bottom[0] * (1 - a)),
    Math.round(g * a + bottom[1] * (1 - a)),
    Math.round(b * a + bottom[2] * (1 - a)),
    1
  ];
}

/** The opaque colour painted behind an element: its own background, then its ancestors'. */
export function backgroundOf(element: Element | null): Rgba {
  const layers: Rgba[] = [];
  for (let node = element; node; node = node.parentElement) {
    const layer = resolve(getComputedStyle(node).backgroundColor);
    if (layer[3] > 0) layers.push(layer);
    if (layer[3] === 1) break;
  }
  return layers.reduceRight<Rgba>((below, layer) => over(layer, below), [255, 255, 255, 1]);
}

/** Contrast of a computed colour against what lies behind `behind`. */
export function contrastAgainst(color: string, behind: Element | null): number {
  const background = backgroundOf(behind);
  return contrastRatio(hex(over(resolve(color), background)), hex(background));
}
