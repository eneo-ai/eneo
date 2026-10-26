// One description of how a chart is drawn, read by the view in the browser and by the image
// renderer in a sandbox child, so the picture a reader exports is the chart they looked at.
import type { EChartsCoreOption } from "echarts/core";
import type { ChartSpec } from "./spec";

/**
 * Categorical colours in a fixed order, stepped for each surface so adjacent series stay apart
 * for readers with a colour-vision deficiency. A series keeps its slot whatever else is hidden.
 */
export const PALETTE = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
} as const;

export type ChartStyle = {
  dark: boolean;
  locale: string;
  ink: string;
  inkSecondary: string;
  grid: string;
  axis: string;
  surface: string;
  font: string;
  /** Size of tick, legend and label text in px; a title is drawn larger. */
  textSize: number;
};

/**
 * An interval around one line (a forecast's P10–P90), filled in that line's colour between
 * `lower` and `upper`. create_chart never draws one: it is for tools that compute an interval.
 */
export type ChartBand = {
  name: string;
  /** The series whose colour the interval takes. */
  series: number;
  lower: (number | null)[];
  upper: (number | null)[];
};
/** A labelled vertical line at a category, such as the day a forecast starts. */
export type ChartMarker = { at: number; label: string };
/**
 * What a tool may draw beyond a create_chart specification: intervals, markers, and labels
 * that are ISO dates (`YYYY-MM-DD`), read as days on the axis and in full under the pointer.
 */
export type PlotSpec = ChartSpec & {
  bands?: ChartBand[];
  markers?: ChartMarker[];
  dates?: boolean;
  /** What a screen reader hears instead of ECharts' own generated, English description. */
  description?: string;
};

/** What the reader has chosen in the view: the series left showing and the zoomed range. */
export type ChartViewState = {
  selected: Record<string, boolean>;
  zoom: { start: number; end: number };
};

/**
 * The image is always drawn light, in a font the image carries, and on white: it ends up on
 * the page of a document as often as in the chat.
 */
export function imageStyle(width: number, locale: string): ChartStyle {
  const scale = Math.min(1.6, Math.max(0.8, width / 1200));
  return {
    dark: false,
    locale,
    ink: "#0b0b0b",
    inkSecondary: "#52514e",
    grid: "#e6e5e1",
    axis: "#c3c2b7",
    surface: "#ffffff",
    font: "'DejaVu Sans', Helvetica, Arial, sans-serif",
    textSize: Math.round(11 * scale),
  };
}

/** Up to this many categories, every one is named on its axis. */
const NAMED_CATEGORIES = 40;

// Control characters have no place in a label, and none in the XML of an image.
const clean = (text: string) => text.replace(/[\x00-\x1f\x7f]/g, " ");
// Text is not measured where the image is drawn; this is close enough to lay it out.
const textWidth = (text: string, size: number) => text.length * size * 0.58;

function formats(spec: PlotSpec, style: ChartStyle, digits: number) {
  const numbers = new Intl.NumberFormat(style.locale, { maximumFractionDigits: digits });
  const number = (value: number) => numbers.format(value);
  const short = new Intl.DateTimeFormat(style.locale, { day: "numeric", month: "short", timeZone: "UTC" });
  const long = new Intl.DateTimeFormat(style.locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
  const date = (label: string, format: Intl.DateTimeFormat) => {
    const time = Date.parse(`${label}T00:00:00Z`);
    return Number.isNaN(time) ? label : format.format(time);
  };
  return {
    number,
    // A number and its unit stay on one line.
    value: (value: number) => `${number(value)}${spec.unit ? `\u00a0${spec.unit}` : ""}`,
    /** A category as the axis names it, and in full where there is room for it. */
    label: (label: string) => (spec.dates ? date(label, short) : label),
    fullLabel: (label: string) => (spec.dates ? date(label, long) : label),
  };
}

/** A palette colour with the opacity an interval is filled with on this surface. */
function intervalColor(style: ChartStyle, series: number): string {
  const palette = PALETTE[style.dark ? "dark" : "light"];
  return `${palette[series % palette.length]}${style.dark ? "47" : "2e"}`;
}

/**
 * Each interval as two stacked series named like it: the lower bound, drawn as nothing, and
 * the width above it, filled. Hiding the name in the legend hides both.
 */
function intervalSeries(spec: PlotSpec, style: ChartStyle) {
  return (spec.bands ?? []).flatMap((band, index) => {
    const color = intervalColor(style, band.series);
    const shared = {
      name: clean(band.name),
      type: "line",
      stack: `interval-${index}`,
      // The width rises from the lower bound whatever its sign; by default ECharts stacks a
      // value only on values of the same sign, and a bound below zero would shade from zero.
      stackStrategy: "all",
      symbol: "none",
      silent: true,
      connectNulls: false,
      lineStyle: { opacity: 0 },
      itemStyle: { color },
      z: 1,
    };
    return [
      { ...shared, id: `interval-${index}-lower`, data: band.lower },
      {
        ...shared,
        id: `interval-${index}-width`,
        areaStyle: { color, opacity: 1 },
        data: band.lower.map((low, i) => {
          const high = band.upper[i];
          return low === null || high === null || high === undefined ? null : high - low;
        }),
        ...isolatedSpans(band.lower, band.upper, color),
      },
    ];
  });
}

/** The days of a line with no neighbouring value: no segment reaches them. */
function alone(values: readonly (number | null | undefined)[]): number[] {
  const known = (i: number) => values[i] !== null && values[i] !== undefined;
  return values.flatMap((_, i) => (known(i) && !known(i - 1) && !known(i + 1) ? [i] : []));
}

/**
 * A line whose points are hidden draws a day between two gaps (or a one-day forecast) as
 * nothing at all; such days are drawn as a dot of the series' colour.
 */
function isolatedDots(values: readonly (number | null)[], size: number) {
  const data = alone(values).map((i) => ({ coord: [i, values[i]] }));
  return data.length ? { markPoint: { symbol: "circle", symbolSize: size, silent: true, label: { show: false }, data } } : {};
}

/** An interval's day with no neighbour has no area to fill; it is drawn as a bar from bound to bound. */
function isolatedSpans(lower: readonly (number | null)[], upper: readonly (number | null)[], color: string) {
  const data = alone(lower)
    .filter((i) => upper[i] !== null && upper[i] !== undefined)
    .map((i) => [{ coord: [i, lower[i]] }, { coord: [i, upper[i]] }]);
  return data.length
    ? { markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color, width: 6, type: "solid", opacity: 1 }, data } }
    : {};
}

/**
 * Markers as dashed lines across the plot, each with its own label. They ride on a series of
 * their own without data, so hiding a series in the legend never hides a marker.
 */
function markerSeries(spec: PlotSpec, style: ChartStyle) {
  if (!spec.markers?.length) return [];
  return [
    {
      id: "markers",
      type: "line",
      data: [],
      silent: true,
      markLine: {
        silent: true,
        symbol: "none",
        lineStyle: { color: style.inkSecondary, type: "dashed", width: 1 },
        label: { color: style.inkSecondary, fontSize: style.textSize, position: "end" },
        data: spec.markers.map((marker) => ({ xAxis: marker.at, label: { formatter: clean(marker.label) } })),
      },
    },
  ];
}

type TooltipPoint = { seriesId?: string; seriesName?: string; dataIndex: number; value: unknown; marker?: unknown; axisValue?: unknown };

/**
 * The tooltip of a chart with intervals or dates: the day in full, every line's value, and
 * each interval as lowest–highest rather than as its two helper series.
 */
function intervalTooltip(spec: PlotSpec, format: ReturnType<typeof formats>) {
  return (input: unknown) => {
    const points = (Array.isArray(input) ? input : [input]) as TooltipPoint[];
    const index = points[0]?.dataIndex ?? 0;
    const lines = [format.fullLabel(String(points[0]?.axisValue ?? spec.labels[index] ?? ""))];
    for (const point of points) {
      if (point.seriesId?.startsWith("interval-") || typeof point.value !== "number") continue;
      lines.push(`${typeof point.marker === "string" ? point.marker : ""}${point.seriesName}: ${format.value(point.value)}`);
    }
    (spec.bands ?? []).forEach((band, b) => {
      // A hidden interval leaves no point of its own under the pointer.
      if (!points.some((point) => point.seriesId === `interval-${b}-width`)) return;
      const low = band.lower[index];
      const high = band.upper[index];
      if (low == null || high == null || low === high) return;
      lines.push(`${clean(band.name)}: ${format.number(low)}–${format.value(high)}`);
    });
    return lines.join("\n");
  };
}

function common(style: ChartStyle) {
  return {
    animation: false,
    color: [...PALETTE[style.dark ? "dark" : "light"]],
    backgroundColor: style.surface,
    textStyle: { color: style.ink, fontFamily: style.font, fontSize: style.textSize },
  };
}

function axes(spec: PlotSpec, style: ChartStyle, format: ReturnType<typeof formats>) {
  const scatter = spec.type === "scatter";
  const axis = {
    nameTextStyle: { color: style.inkSecondary, fontSize: style.textSize },
    axisLabel: { color: style.inkSecondary, fontSize: style.textSize },
    axisLine: { lineStyle: { color: style.axis } },
    axisTick: { lineStyle: { color: style.axis } },
    splitLine: { lineStyle: { color: style.grid } },
    nameLocation: "middle",
  };
  return {
    xAxis: {
      ...axis,
      ...(scatter
        ? {
            type: "value",
            scale: true,
            axisLabel: { ...axis.axisLabel, formatter: format.number },
          }
        : {
            type: "category",
            data: spec.labels.map(clean),
            // A handful of categories are all named; among many, names that collide give way.
            axisLabel: {
              ...axis.axisLabel,
              hideOverlap: true,
              ...(spec.labels.length <= NAMED_CATEGORIES ? { interval: 0 } : {}),
              ...(spec.dates ? { formatter: format.label } : {}),
            },
          }),
      ...(spec.x_label ? { name: clean(spec.x_label) } : {}),
      nameGap: Math.round(style.textSize * 2.6),
    },
    yAxis: {
      ...axis,
      type: "value",
      // Bars are read from zero; a line or a cloud of points is read by its shape.
      scale: spec.type !== "bar",
      axisLabel: { ...axis.axisLabel, formatter: format.value },
      ...(spec.y_label ? { name: clean(spec.y_label) } : {}),
      nameGap: Math.round(style.textSize * 4.5),
    },
  };
}

/** The data of every series; how each is drawn is added by the caller. */
function seriesData(spec: ChartSpec) {
  return spec.series.map((series, index) => ({
    id: `series-${index}`,
    name: clean(series.name),
    type: spec.type,
    ...(spec.stacked ? { stack: "values" } : {}),
    connectNulls: false,
    data:
      spec.type === "scatter"
        ? series.values.map((value, i) => [series.x![i], value])
        : series.values,
  }));
}

function slices(spec: ChartSpec) {
  return spec.labels.map((name, i) => ({ name: clean(name), value: spec.series[0]!.values[i] }));
}

/**
 * The chart as the view draws it: values under the pointer, series the reader can hide and an
 * x axis they can zoom. Only validated chart data comes in, never ECharts options of a caller.
 */
export function chartOptions(
  spec: PlotSpec,
  style: ChartStyle,
  view: ChartViewState,
): EChartsCoreOption {
  const format = formats(spec, style, 12);
  const plotted = !!spec.bands?.length || !!spec.dates;
  const base = {
    ...common(style),
    // Patterns tell filled series apart without colour; an interval is told apart by its shape
    // and its label, and a pattern over it would only blur the figures under it.
    aria: {
      enabled: true,
      decal: { show: !spec.bands?.length },
      ...(spec.description ? { label: { description: clean(spec.description) } } : {}),
    },
    // The view draws its own legend; this one only carries which series are showing.
    legend: { show: false, selected: view.selected },
    // richText renders inside SVG; no labels or values become HTML.
    tooltip: {
      trigger: spec.type === "pie" || spec.type === "scatter" ? "item" : "axis",
      renderMode: "richText",
      confine: true,
      backgroundColor: style.surface,
      borderColor: style.axis,
      textStyle: { color: style.ink, fontSize: style.textSize },
      ...(plotted
        ? { formatter: intervalTooltip(spec, format) }
        : {
            valueFormatter: (value: unknown) =>
              typeof value === "number" ? format.value(value) : String(value),
          }),
    },
  };
  if (spec.type === "pie")
    return {
      ...base,
      series: [
        {
          type: "pie",
          radius: [0, "68%"],
          label: { color: style.ink, formatter: (slice: { name: string }) => slice.name },
          itemStyle: { borderColor: style.surface, borderWidth: 2 },
          data: slices(spec),
        },
      ],
    };
  return {
    ...base,
    // The margins are the outer edge: tick labels and axis names are kept inside them.
    grid: {
      left: 16,
      right: 24,
      top: 24,
      bottom: 44,
      outerBoundsMode: "same",
      outerBoundsContain: "all",
    },
    ...axes(spec, style, format),
    dataZoom: [
      // The range slider owns zoom. An inside-zoom controller captures wheel
      // events even when its zoomOnMouseWheel option is disabled, preventing
      // the containing side panel from scrolling.
      {
        type: "slider",
        xAxisIndex: 0,
        bottom: 8,
        height: 22,
        ...view.zoom,
        // The ends of the range are read off the axis; written beside the slider they are cut
        // off at the edge of the view.
        showDetail: false,
      },
    ],
    series: [
      ...seriesData(spec).map((series, index) => ({
        ...series,
        symbolSize: 7,
        // A day-by-day series is read as a line; its points show under the pointer.
        ...(spec.dates ? { showSymbol: false, ...isolatedDots(spec.series[index]!.values, 7) } : {}),
      })),
      ...intervalSeries(spec, style),
      ...markerSeries(spec, style),
    ],
  };
}

/**
 * The chart as an image: nothing to hover or toggle, so the title, the legend and the values
 * a reader would otherwise point at are drawn into it.
 */
export function imageOptions(
  spec: PlotSpec,
  style: ChartStyle,
  size: { width: number; height: number },
): EChartsCoreOption {
  const { width, height } = size;
  const text = style.textSize;
  const scale = text / 11;
  const edge = Math.round(24 * scale);
  const format = formats(spec, style, 2);
  let top = Math.round(18 * scale);
  const title = spec.title
    ? {
        text: clean(spec.title),
        left: "center",
        top,
        textStyle: {
          color: style.ink,
          fontSize: Math.round(text * 1.5),
          fontWeight: 600,
          width: width - 2 * edge,
          overflow: "truncate",
        },
      }
    : undefined;
  if (title) top += Math.round(text * 2.8);

  if (spec.type === "pie") {
    const shares = new Intl.NumberFormat(style.locale, { maximumFractionDigits: 1 });
    return {
      ...common(style),
      ...(title ? { title } : {}),
      series: [
        {
          type: "pie",
          radius: [0, "62%"],
          center: ["50%", Math.round((top + height - edge) / 2)],
          // Each slice is named where it is, so identity never rests on colour alone.
          label: {
            color: style.ink,
            fontSize: text,
            formatter: (slice: { name: string; percent: number }) =>
              `${slice.name}: ${shares.format(slice.percent)}\u00a0%`,
          },
          labelLine: { lineStyle: { color: style.axis } },
          itemStyle: { borderColor: style.surface, borderWidth: Math.round(2 * scale) },
          data: slices(spec),
        },
      ],
    };
  }

  // A single series is named by the title; two or more get a legend, and so does an interval.
  const names =
    spec.series.length > 1 || spec.bands?.length
      ? [...spec.series.map((series) => clean(series.name)), ...(spec.bands ?? []).map((band) => clean(band.name))]
      : [];
  let legend: Record<string, unknown> = { show: false };
  if (names.length) {
    const swatch = Math.round(12 * scale);
    const gap = Math.round(20 * scale);
    let rows = 1;
    let x = 0;
    for (const name of names) {
      const entry = swatch + 6 * scale + textWidth(name, text) + gap;
      if (x > 0 && x + entry > width - 2 * edge) {
        rows++;
        x = 0;
      }
      x += entry;
    }
    legend = {
      show: true,
      data: names,
      top,
      left: edge,
      right: edge,
      selectedMode: false,
      icon: "roundRect",
      itemWidth: swatch,
      itemHeight: swatch,
      itemGap: gap,
      textStyle: { color: style.ink, fontSize: text },
    };
    top += Math.round(rows * text * 2.1 + text * 0.6);
  }

  const drawn = seriesData(spec);
  const points = spec.series.reduce((sum, series) => sum + series.values.length, 0);
  const symbols = !spec.dates && points <= 60;
  // Two to four lines are named at their last point as well. Not beside an interval: its
  // lines end mid-plot, and the legend already names every part.
  const direct = spec.type === "line" && !spec.bands?.length && spec.series.length > 1 && spec.series.length <= 4;
  const directRoom = direct
    ? Math.min(160 * scale, Math.max(...names.map((name) => textWidth(name, text)))) + 12 * scale
    : 0;
  const radius = Math.round(4 * scale);
  const groups = spec.labels.length;
  const bars = groups * (spec.stacked ? 1 : spec.series.length);
  const valueLabels = spec.type === "bar" && bars <= 16;
  const label = {
    show: true,
    position: "top",
    color: style.inkSecondary,
    fontSize: text,
    formatter: (point: { value: unknown }) =>
      typeof point.value === "number" ? format.value(point.value) : "",
  };

  const series: Record<string, unknown>[] = drawn.map((entry, index) => {
    if (spec.type === "bar")
      return {
        ...entry,
        barGap: "6%",
        barCategoryGap: "28%",
        ...(spec.stacked
          ? {}
          : {
              itemStyle: { borderRadius: [radius, radius, 0, 0] },
              ...(valueLabels ? { label } : {}),
              // A bar below zero is rounded, and labelled, at its far end.
              data: spec.series[index]!.values.map((value) =>
                value !== null && value < 0
                  ? {
                      value,
                      itemStyle: { borderRadius: [0, 0, radius, radius] },
                      label: { position: "bottom" },
                    }
                  : value,
              ),
            }),
      };
    if (spec.type === "line")
      return {
        ...entry,
        symbol: "circle",
        symbolSize: Math.round(8 * scale),
        // Few points are drawn as points; a day-by-day series is a line, its lone days dots.
        showSymbol: symbols,
        ...(symbols ? {} : isolatedDots(spec.series[index]!.values, Math.round(8 * scale))),
        lineStyle: { width: 2 * scale },
        itemStyle: { borderColor: style.surface, borderWidth: Math.round(2 * scale) },
        ...(direct
          ? {
              endLabel: {
                show: true,
                color: style.ink,
                fontSize: text,
                width: directRoom,
                overflow: "truncate",
                formatter: (point: { seriesName: string }) => point.seriesName,
              },
            }
          : {}),
      };
    return {
      ...entry,
      symbolSize: Math.round(10 * scale),
      itemStyle: { opacity: 1, borderColor: style.surface, borderWidth: Math.round(2 * scale) },
    };
  });
  series.push(...intervalSeries(spec, style), ...markerSeries(spec, style));
  if (spec.stacked && valueLabels) {
    // The sum of each stack, written above it by an unseen bar as tall as what rises from zero.
    const totals = spec.labels.map((_, i) =>
      spec.series.reduce((sum, entry) => sum + (entry.values[i] ?? 0), 0),
    );
    series.push({
      type: "bar",
      barGap: "-100%",
      silent: true,
      itemStyle: { color: "transparent" },
      data: spec.labels.map((_, i) =>
        spec.series.reduce((sum, entry) => sum + Math.max(0, entry.values[i] ?? 0), 0),
      ),
      label: {
        ...label,
        formatter: (point: { dataIndex: number }) => format.value(totals[point.dataIndex] ?? 0),
      },
    });
  }

  // Long category names are tilted rather than dropped. Dates stay upright: among many days,
  // the ones that would collide give way and the rest still read as a time axis.
  const slot = (width - 2 * edge - 60 * scale) / Math.max(1, groups);
  const widest = Math.max(0, ...spec.labels.map((name) => textWidth(clean(name), text)));
  const tilted = !spec.dates && spec.type !== "scatter" && groups > 1 && widest > slot - 6 * scale;
  const { xAxis, yAxis } = axes(spec, style, format);
  return {
    ...common(style),
    ...(title ? { title } : {}),
    legend,
    grid: {
      left: edge,
      right: edge + Math.round(directRoom),
      top,
      bottom: Math.round(edge * 0.7),
      outerBoundsMode: "same",
      outerBoundsContain: "all",
    },
    xAxis: tilted
      ? {
          ...xAxis,
          axisLabel: {
            ...xAxis.axisLabel,
            rotate: 35,
            width: Math.round(170 * scale),
            overflow: "truncate",
          },
        }
      : xAxis,
    yAxis,
    series,
  };
}
