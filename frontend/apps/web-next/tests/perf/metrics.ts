// Pure helpers of the performance baseline (baseline.perf.ts), unit-tested in
// src/test/perf-metrics.test.ts.

export type Samples = Record<string, Record<string, number[]>>;
/**
 * `mean` is there because some metrics are bimodal (the chat greeting paints at
 * about 350 or 450 ms), which makes their median jump between runs; gates on
 * such a metric compare p75 or mean.
 */
export type Summary = { median: number; p75: number; mean: number };
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
  const metrics: Record<string, Record<string, Summary>> = {};
  for (const [route, byMetric] of Object.entries(samples)) {
    metrics[route] = {};
    for (const [metric, values] of Object.entries(byMetric)) {
      metrics[route][metric] = {
        median: quantile(values, 0.5),
        p75: quantile(values, 0.75),
        mean: values.reduce((sum, value) => sum + value, 0) / values.length
      };
    }
  }
  return metrics;
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
