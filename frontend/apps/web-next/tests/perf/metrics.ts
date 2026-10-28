// Pure helpers of the performance baseline (baseline.perf.ts), unit-tested in
// src/test/perf-metrics.test.ts.

/** The route whose page also measures chat readiness, navigation, TTFT and INP. */
export const CHAT_ROUTE = "/spaces/personal/chat";

export type Samples = Record<string, Record<string, number[]>>;
export type Summary = { median: number; p75: number };
export type Metrics = Record<string, Record<string, Summary>>;
/** An Event Timing entry as the page records it. */
export type EventEntry = { interactionId: number; startTime: number; duration: number };

/** RUNS from the environment: a positive integer, default 10. */
export function parseRuns(value: string | undefined) {
  const runs = Number(value ?? 10);
  if (!Number.isInteger(runs) || runs < 1) {
    throw new Error(`RUNS must be a positive integer, got ${JSON.stringify(value)}`);
  }
  return runs;
}

export function quantile(values: number[], q: number) {
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * q;
  const low = sorted[Math.floor(index)] ?? 0;
  const high = sorted[Math.ceil(index)] ?? 0;
  return low + (high - low) * (index - Math.floor(index));
}

export function summarize(samples: Samples) {
  const metrics: Metrics = {};
  for (const [route, byMetric] of Object.entries(samples)) {
    metrics[route] = {};
    for (const [metric, values] of Object.entries(byMetric)) {
      metrics[route][metric] = { median: quantile(values, 0.5), p75: quantile(values, 0.75) };
    }
  }
  return metrics;
}

/**
 * The stability rule (owner decision, 2026-10-28): two consecutive runs on the
 * same build and machine are stable when every metric's medians differ by at
 * most 15% of the larger one. INP and CLS are judged in absolute terms
 * (rescope-v1: INP comes in 8 ms Event Timing steps, CLS sits around 0.005):
 * medians at most one 8 ms step or 0.01 apart.
 *
 * The chat route's LCP is informational (`stable: null`, and no comparison
 * rule): its largest paint is always the greeting h1, whose text useNow() keeps
 * empty in the server HTML and through hydration, so it paints only after a
 * second, post-hydration React render, later than the composer the user waits
 * for. The chat page's load metric is chat readiness (coldChatReadyMs,
 * warmChatReadyMs). On Next both still fall in two clusters: the page streams in
 * a Suspense boundary that React reveals on the next frame when it arrives
 * before the shell's first frame, and otherwise about 300 ms after that frame.
 *
 * A measurement only one of the runs has is never stable.
 */
export function compareRuns(first: Metrics, second: Metrics) {
  const routes = new Set([...Object.keys(first), ...Object.keys(second)]);
  return [...routes].flatMap((route) => {
    const metrics = new Set([
      ...Object.keys(first[route] ?? {}),
      ...Object.keys(second[route] ?? {})
    ]);
    return [...metrics].map((metric) => {
      const a = first[route]?.[metric]?.median ?? Number.NaN;
      const b = second[route]?.[metric]?.median ?? Number.NaN;
      const apart = Math.abs(a - b);
      let stable: boolean | null;
      if (Number.isNaN(apart)) stable = false;
      else if (route === CHAT_ROUTE && /^(cold|warm)LcpMs$/.test(metric)) stable = null;
      else if (metric === "inpMs") stable = apart <= 8;
      else if (metric.endsWith("Cls")) stable = apart <= 0.01;
      else stable = apart <= 0.15 * Math.max(a, b);
      return { route, metric, medians: [a, b], stable };
    });
  });
}

/**
 * The slowest interaction that started at or after `since`: only entries with an
 * interactionId count (hover and other non-interaction events have 0), as in the
 * Event Timing spec's INP example.
 */
export function worstInteractionMs(entries: EventEntry[], since: number) {
  return entries
    .filter((entry) => entry.interactionId > 0 && entry.startTime >= since)
    .reduce((worst, entry) => Math.max(worst, entry.duration), 0);
}
