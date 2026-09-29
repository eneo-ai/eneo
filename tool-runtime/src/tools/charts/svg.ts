// Pure SVG chart drawing: no DOM, no native code, deterministic output for a given spec.
import type { ChartSpec } from "./spec";

export type SvgOptions = {
  width: number;
  height: number;
  locale: "sv-SE" | "en-GB";
  // The widget follows the host's theme; the PNG is always drawn on the light surface.
  theme?: "light" | "dark";
  // Font stack override for the widget, where the host names its own fonts.
  font?: string;
};

// Validated categorical order (adjacent-pair colour-vision safe on a light surface).
export const palette = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
  "#e34948",
] as const;
type Colors = Record<"surface" | "ink" | "inkSecondary" | "grid" | "axis", string>;
const themes: Record<"light" | "dark", Colors> = {
  light: {
    surface: "#fcfcfb",
    ink: "#0b0b0b",
    inkSecondary: "#52514e",
    grid: "#e6e5e1",
    axis: "#c3c2b7",
  },
  dark: {
    surface: "#1b1b1a",
    ink: "#f2f1ee",
    inkSecondary: "#b3b1ab",
    grid: "#34332f",
    axis: "#5b5a55",
  },
};
const DEFAULT_FONT = "'DejaVu Sans', Helvetica, Arial, sans-serif";

export function escapeXml(text: string): string {
  return text.replace(/[<>&"']/g, (c) => {
    switch (c) {
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "&":
        return "&amp;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}
const clean = (text: string) => text.replace(/[\x00-\x1f\x7f]/g, " ");
const textWidth = (text: string, size: number) => text.length * size * 0.58;
function truncate(text: string, size: number, maxWidth: number): string {
  if (textWidth(text, size) <= maxWidth) return text;
  const chars = Math.max(1, Math.floor(maxWidth / (size * 0.58)) - 1);
  return `${text.slice(0, chars)}…`;
}
const round = (n: number) => Math.round(n * 100) / 100;
function niceStep(range: number, count: number): number {
  const rough = range / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const factor =
    residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 2.5 ? 2.5 : residual <= 5 ? 5 : 10;
  return factor * magnitude;
}
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    if (min === 0) return [0, 1];
    min = min > 0 ? 0 : min * 2;
    max = max > 0 ? max * 2 : 0;
  }
  const step = niceStep(max - min, count);
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(round(v));
  return ticks;
}
type Scale = { min: number; max: number; ticks: number[] };
function scaleFor(values: number[], includeZero: boolean): Scale {
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (includeZero) {
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  const ticks = niceTicks(min, max);
  return { min: ticks[0]!, max: ticks[ticks.length - 1]!, ticks };
}

export function renderSvg(spec: ChartSpec, options: SvgOptions): string {
  const { width, height } = options;
  const {
    surface: SURFACE,
    ink: INK,
    inkSecondary: INK_SECONDARY,
    grid: GRID,
    axis: AXIS,
  } = themes[options.theme ?? "light"];
  const FONT = options.font ?? DEFAULT_FONT;
  const scale = Math.min(1.6, Math.max(0.8, width / 1200));
  const fontSize = Math.round(13 * scale);
  const small = Math.round(11 * scale);
  const numberFormat = new Intl.NumberFormat(options.locale, { maximumFractionDigits: 2 });
  const format = (v: number) => `${numberFormat.format(v)}${spec.unit ? ` ${spec.unit}` : ""}`;
  const parts: string[] = [];
  const text = (
    x: number,
    y: number,
    content: string,
    attributes: Record<string, string | number> = {},
    size = fontSize,
    fill = INK_SECONDARY,
  ) => {
    const attrs = Object.entries(attributes)
      .map(([k, v]) => ` ${k}="${v}"`)
      .join("");
    parts.push(
      `<text x="${round(x)}" y="${round(y)}" font-size="${size}" fill="${fill}"${attrs}>${escapeXml(clean(content))}</text>`,
    );
  };
  let top = 20 * scale;
  if (spec.title) {
    text(
      width / 2,
      top + fontSize,
      truncate(clean(spec.title), fontSize * 1.25, width - 40),
      {
        "text-anchor": "middle",
        "font-weight": "600",
      },
      Math.round(fontSize * 1.25),
      INK,
    );
    top += fontSize * 2.2;
  }
  // Legend: always for two or more series and for pie slices; a single series is named by the title.
  const legendEntries =
    spec.type === "pie"
      ? spec.labels.map((label, i) => ({ label, color: palette[i % palette.length]! }))
      : spec.series.length > 1
        ? spec.series.map((s, i) => ({ label: s.name, color: palette[i]! }))
        : [];
  if (legendEntries.length) {
    const swatch = 12 * scale;
    let x = 24 * scale;
    let y = top + swatch;
    const rowHeight = fontSize * 1.7;
    for (const [k, entry] of legendEntries.entries()) {
      const label = truncate(clean(entry.label), small, width / 3);
      const w = swatch + 6 * scale + textWidth(label, small) + 20 * scale;
      if (x + w > width - 24 * scale && x > 24 * scale) {
        x = 24 * scale;
        y += rowHeight;
      }
      // data-legend lets the widget find the entry for a series; the PNG ignores it.
      parts.push(
        `<rect x="${round(x)}" y="${round(y - swatch)}" width="${round(swatch)}" height="${round(swatch)}" rx="3" fill="${entry.color}" data-legend="${k}"/>`,
      );
      text(x + swatch + 6 * scale, y - 1, label, { "data-legend": k }, small, INK);
      x += w;
    }
    top = y + rowHeight * 0.6;
  }
  const bottomLabel = spec.x_label ? fontSize * 1.8 : 0;
  const leftLabel = spec.y_label ? fontSize * 1.8 : 0;
  const directLabels = spec.type === "line" && spec.series.length > 1 && spec.series.length <= 4;
  const labelRoom = directLabels
    ? Math.min(160 * scale, Math.max(...spec.series.map((s) => textWidth(clean(s.name), small))))
    : 0;
  const right = 28 * scale + (directLabels ? labelRoom + 12 * scale : 0);
  const bottomBase = height - 24 * scale - bottomLabel;

  const body =
    spec.type === "pie"
      ? drawPie()
      : spec.type === "scatter"
        ? drawXY(true)
        : spec.type === "line"
          ? drawXY(false)
          : drawBars();
  parts.push(...body);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="${FONT}"><rect width="${width}" height="${height}" fill="${SURFACE}"/>${parts.join("")}</svg>`;

  function frame(yScale: Scale, xTickLabels: string[] | undefined) {
    const yLabels = yScale.ticks.map(format);
    const yWidth = Math.max(...yLabels.map((l) => textWidth(l, small))) + 12 * scale;
    let left = 24 * scale + leftLabel + yWidth;
    let plotWidth = width - left - right;
    let rotate = false;
    let bottom = bottomBase - fontSize * 1.6;
    if (xTickLabels) {
      const slot = plotWidth / Math.max(1, xTickLabels.length);
      const widest = Math.max(...xTickLabels.map((l) => textWidth(l, small)));
      rotate = widest > slot - 6 * scale && xTickLabels.length > 1;
      if (rotate) {
        const shown = Math.min(widest, 140 * scale);
        bottom = bottomBase - shown * 0.6 - fontSize * 0.6;
        // A rotated label hangs left of its tick; keep the first one inside the image.
        left = Math.max(left, shown * 0.82 - slot / 2 + 8 * scale);
        plotWidth = width - left - right;
      }
    }
    const plotHeight = bottom - top;
    const yFor = (v: number) =>
      bottom - ((v - yScale.min) / (yScale.max - yScale.min)) * plotHeight;
    // Axes and grid are pushed straight to the document so they sit beneath the marks.
    const out = parts;
    for (const [i, tick] of yScale.ticks.entries()) {
      const y = yFor(tick);
      out.push(
        `<line x1="${round(left)}" x2="${round(left + plotWidth)}" y1="${round(y)}" y2="${round(y)}" stroke="${tick === 0 ? AXIS : GRID}" stroke-width="1"/>`,
      );
      out.push(
        `<text x="${round(left - 8 * scale)}" y="${round(y + small * 0.35)}" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="end">${escapeXml(yLabels[i]!)}</text>`,
      );
    }
    if (spec.y_label)
      out.push(
        `<text transform="translate(${round(20 * scale + fontSize * 0.6)} ${round(top + plotHeight / 2)}) rotate(-90)" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="middle">${escapeXml(truncate(clean(spec.y_label), small, plotHeight))}</text>`,
      );
    if (spec.x_label)
      out.push(
        `<text x="${round(left + plotWidth / 2)}" y="${round(height - 10 * scale)}" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="middle">${escapeXml(truncate(clean(spec.x_label), small, plotWidth))}</text>`,
      );
    return { left, plotWidth, bottom, plotHeight, yFor, rotate };
  }
  // Series and value position of a mark, so the widget can show the value under the pointer.
  function mark(series: number, index: number): string {
    return ` data-series="${series}" data-index="${index}"`;
  }
  function xTick(out: string[], x: number, y: number, label: string, rotate: boolean) {
    const shown = truncate(clean(label), small, rotate ? 140 * scale : 200 * scale);
    if (rotate)
      out.push(
        `<text transform="translate(${round(x)} ${round(y)}) rotate(-35)" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="end">${escapeXml(shown)}</text>`,
      );
    else
      out.push(
        `<text x="${round(x)}" y="${round(y)}" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="middle">${escapeXml(shown)}</text>`,
      );
  }
  function barPath(x: number, base: number, end: number, w: number): string {
    const r = Math.min(4 * scale, w / 2, Math.abs(end - base));
    if (end <= base)
      return `M${round(x)} ${round(base)}V${round(end + r)}a${r} ${r} 0 0 1 ${r} -${r}H${round(x + w - r)}a${r} ${r} 0 0 1 ${r} ${r}V${round(base)}Z`;
    return `M${round(x)} ${round(base)}V${round(end - r)}a${r} ${r} 0 0 0 ${r} ${r}H${round(x + w - r)}a${r} ${r} 0 0 0 ${r} -${r}V${round(base)}Z`;
  }
  function drawBars(): string[] {
    const n = spec.labels.length;
    const values: number[] = [];
    if (spec.stacked) {
      for (let i = 0; i < n; i++) {
        let up = 0;
        let down = 0;
        for (const s of spec.series) {
          const v = s.values[i];
          if (v === null || v === undefined) continue;
          if (v >= 0) up += v;
          else down += v;
        }
        values.push(up, down);
      }
    } else for (const s of spec.series) for (const v of s.values) if (v !== null) values.push(v);
    const yScale = scaleFor(values.length ? values : [0], true);
    const { left, plotWidth, bottom, yFor, rotate } = frame(yScale, spec.labels);
    const out: string[] = [];
    const group = plotWidth / Math.max(1, n);
    const inner = group * 0.72;
    const perBar = spec.stacked
      ? inner
      : (inner - 2 * scale * (spec.series.length - 1)) / spec.series.length;
    const baseline = yFor(0);
    const totalBars = n * (spec.stacked ? 1 : spec.series.length);
    const showValues = totalBars <= 16;
    for (let i = 0; i < n; i++) {
      const groupX = left + i * group + (group - inner) / 2;
      let up = 0;
      let down = 0;
      for (const [k, s] of spec.series.entries()) {
        const v = s.values[i];
        if (v === null || v === undefined) continue;
        const color = palette[k]!;
        if (spec.stacked) {
          const start = v >= 0 ? up : down;
          const end = start + v;
          if (v >= 0) up = end;
          else down = end;
          const y0 = yFor(start);
          const y1 = yFor(end);
          const gap = 2 * scale;
          const isOuter = k === spec.series.length - 1;
          const rect = isOuter
            ? barPath(groupX, y0, y1, perBar)
            : `<rect x="${round(groupX)}" y="${round(Math.min(y0, y1))}" width="${round(perBar)}" height="${round(Math.max(0, Math.abs(y1 - y0) - gap))}" fill="${color}"${mark(k, i)}/>`;
          out.push(isOuter ? `<path d="${rect}" fill="${color}"${mark(k, i)}/>` : rect);
        } else {
          const x = groupX + k * (perBar + 2 * scale);
          out.push(
            `<path d="${barPath(x, baseline, yFor(v), perBar)}" fill="${color}"${mark(k, i)}/>`,
          );
          if (showValues)
            out.push(
              `<text x="${round(x + perBar / 2)}" y="${round(v >= 0 ? yFor(v) - 5 * scale : yFor(v) + small + 3 * scale)}" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="middle">${escapeXml(format(v))}</text>`,
            );
        }
      }
      if (spec.stacked && showValues && (up || down))
        out.push(
          `<text x="${round(groupX + perBar / 2)}" y="${round(yFor(up) - 5 * scale)}" font-size="${small}" fill="${INK_SECONDARY}" text-anchor="middle">${escapeXml(format(up + down))}</text>`,
        );
      xTick(out, left + i * group + group / 2, bottom + fontSize * 1.2, spec.labels[i]!, rotate);
    }
    return out;
  }
  function drawXY(scatter: boolean): string[] {
    const ys: number[] = [];
    const xs: number[] = [];
    for (const s of spec.series) {
      for (const v of s.values) if (v !== null) ys.push(v);
      if (scatter) xs.push(...s.x!);
    }
    const yScale = scaleFor(ys.length ? ys : [0], false);
    const n = spec.labels.length;
    const xScale = scatter ? scaleFor(xs.length ? xs : [0], false) : undefined;
    const { left, plotWidth, bottom, yFor, rotate } = frame(
      yScale,
      scatter ? undefined : spec.labels,
    );
    const out: string[] = [];
    const xFor = scatter
      ? (v: number) => left + ((v - xScale!.min) / (xScale!.max - xScale!.min)) * plotWidth
      : (i: number) => left + (n === 1 ? plotWidth / 2 : (i / (n - 1)) * plotWidth);
    if (scatter) {
      for (const tick of xScale!.ticks) {
        const x = xFor(tick);
        out.push(
          `<line x1="${round(x)}" x2="${round(x)}" y1="${round(top)}" y2="${round(bottom)}" stroke="${GRID}" stroke-width="1"/>`,
        );
        xTick(out, x, bottom + fontSize * 1.2, format(tick), false);
      }
    } else {
      const widest = Math.max(...spec.labels.map((l) => textWidth(clean(l), small)), 1);
      const stride = rotate
        ? Math.ceil((n * small * 1.4) / plotWidth)
        : Math.ceil((n * (widest + 10)) / plotWidth);
      for (let i = 0; i < n; i += Math.max(1, stride))
        xTick(out, xFor(i), bottom + fontSize * 1.2, spec.labels[i]!, rotate);
    }
    const totalPoints = spec.series.reduce((sum, s) => sum + s.values.length, 0);
    const markers = scatter || totalPoints <= 60;
    const r = (scatter ? 5 : 4) * scale;
    for (const [k, s] of spec.series.entries()) {
      const color = palette[k]!;
      if (!scatter) {
        let d = "";
        let pen = false;
        for (const [i, v] of s.values.entries()) {
          if (v === null) {
            pen = false;
            continue;
          }
          d += `${pen ? "L" : "M"}${round(xFor(i))} ${round(yFor(v))}`;
          pen = true;
        }
        if (d)
          out.push(
            `<path d="${d}" fill="none" stroke="${color}" stroke-width="${2 * scale}" stroke-linejoin="round" stroke-linecap="round"/>`,
          );
      }
      if (markers)
        for (const [i, v] of s.values.entries()) {
          if (v === null) continue;
          const cx = scatter ? xFor(s.x![i]!) : xFor(i);
          out.push(
            `<circle cx="${round(cx)}" cy="${round(yFor(v))}" r="${round(r)}" fill="${color}" stroke="${SURFACE}" stroke-width="${2 * scale}"${mark(k, i)}/>`,
          );
        }
      // Direct label at the last point so identity never rests on colour alone.
      if (directLabels) {
        const lastIndex = s.values
          .map((v, i) => (v === null ? -1 : i))
          .reduce((a, b) => Math.max(a, b), -1);
        if (lastIndex >= 0)
          out.push(
            `<text x="${round(xFor(lastIndex) + 8 * scale)}" y="${round(yFor(s.values[lastIndex]!) + small * 0.35)}" font-size="${small}" fill="${INK}">${escapeXml(truncate(clean(s.name), small, labelRoom))}</text>`,
          );
      }
    }
    return out;
  }
  function drawPie(): string[] {
    const values = spec.series[0]!.values.map((v) => v ?? 0);
    const total = values.reduce((a, b) => a + b, 0);
    const out: string[] = [];
    const cx = width / 2;
    const cy = top + (bottomBase - top) / 2;
    const radius = Math.max(40, Math.min(width, bottomBase - top) / 2 - 24 * scale);
    let angle = -Math.PI / 2;
    for (const [i, v] of values.entries()) {
      if (v <= 0) continue;
      const share = v / total;
      const end = angle + share * 2 * Math.PI;
      const large = share > 0.5 ? 1 : 0;
      const x1 = cx + radius * Math.cos(angle);
      const y1 = cy + radius * Math.sin(angle);
      const x2 = cx + radius * Math.cos(end);
      const y2 = cy + radius * Math.sin(end);
      const d =
        share >= 0.999999
          ? `M${round(cx)} ${round(cy - radius)}A${round(radius)} ${round(radius)} 0 1 1 ${round(cx - 0.01)} ${round(cy - radius)}Z`
          : `M${round(cx)} ${round(cy)}L${round(x1)} ${round(y1)}A${round(radius)} ${round(radius)} 0 ${large} 1 ${round(x2)} ${round(y2)}Z`;
      out.push(
        `<path d="${d}" fill="${palette[i % palette.length]}" stroke="${SURFACE}" stroke-width="${2 * scale}"${mark(0, i)}/>`,
      );
      if (share >= 0.06) {
        const mid = (angle + end) / 2;
        const lx = cx + radius * 0.62 * Math.cos(mid);
        const ly = cy + radius * 0.62 * Math.sin(mid);
        out.push(
          `<text x="${round(lx)}" y="${round(ly + small * 0.35)}" font-size="${small}" fill="${SURFACE}" font-weight="600" text-anchor="middle">${escapeXml(`${numberFormat.format(Math.round(share * 1000) / 10)} %`)}</text>`,
        );
      }
      angle = end;
    }
    return out;
  }
}
