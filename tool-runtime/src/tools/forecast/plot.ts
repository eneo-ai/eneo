// A forecast as a chart, drawn by Charts: read by the view in the browser and by the image
// renderer in a sandbox child, so an exported picture is the chart the reader looked at.
import type { PlotSpec } from "../charts/options";

export type ForecastPlotTexts = { history: string; median: string; interval: string; start: string };

export const PLOT_TEXTS: Record<"sv" | "en", ForecastPlotTexts> = {
  sv: { history: "Historik", median: "Mest troligt (P50)", interval: "Spann (P10–P90)", start: "Prognos" },
  en: { history: "History", median: "Most likely (P50)", interval: "Interval (P10–P90)", start: "Forecast" },
};

/** What a forecast's chart needs of the tool's result: the recent days and the days ahead. */
export type ForecastSeries = {
  recent: { from: string; values: (number | null)[] };
  forecast: { from: string; days: number; p10: number[]; p50: number[]; p90: number[] };
};

const DAY_MS = 86_400_000;

/**
 * The recent history, then the median and its interval. Both start at the last observed day,
 * so the forecast continues the line; after a day without a value they start on their own.
 */
export function forecastPlot(data: ForecastSeries, texts: ForecastPlotTexts, title?: string): PlotSpec {
  const recent = data.recent.values;
  const ahead = data.forecast.days;
  const start = Date.parse(`${data.recent.from}T00:00:00Z`);
  const labels = Array.from({ length: recent.length + ahead }, (_, day) =>
    new Date(start + day * DAY_MS).toISOString().slice(0, 10),
  );
  const empty = (days: number) => Array<null>(Math.max(0, days)).fill(null);
  const last = recent.at(-1) ?? null;
  const fromLast = (values: number[]) => [...empty(recent.length - 1), ...(recent.length ? [last] : []), ...values];
  return {
    type: "line",
    ...(title ? { title } : {}),
    labels,
    stacked: false,
    series: [
      { name: texts.history, values: [...recent, ...empty(ahead)] },
      { name: texts.median, values: fromLast(data.forecast.p50) },
    ],
    bands: [
      {
        name: texts.interval,
        series: 1,
        lower: fromLast(data.forecast.p10),
        upper: fromLast(data.forecast.p90),
      },
    ],
    markers: [{ at: recent.length, label: texts.start }],
    dates: true,
  };
}
