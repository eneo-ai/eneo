// Runs inside sandbox children only: compares a forecast of the last days with what happened.
import type { ForecastConfig } from "./config";
import type { Interval } from "./ports";

/** How far back the baseline looks for the same weekday. */
const BASELINE_WEEKS = 4;

export type HoldoutUnavailable = "SHORT_HISTORY" | "TOO_MANY_MISSING" | "NO_OUTCOME" | "NO_BASELINE";

/** Why the check could not be made, in words the model can pass on. */
export const HOLDOUT_REASONS: Record<HoldoutUnavailable, string> = {
  SHORT_HISTORY: "The history before the last days is too short to forecast them.",
  TOO_MANY_MISSING: "Too many days before the last days have no value.",
  NO_OUTCOME: "None of the last days has a value to compare with.",
  NO_BASELINE: "Some weekdays have no value in the four weeks before the last days.",
};

/**
 * The forecast the model would have made for the last `horizon` days, scored on the days that
 * have a value: the mean absolute error of the median, the same for the baseline (the last
 * week before those days, repeated: each day takes the value of its weekday), and how many
 * outcomes fell inside P10–P90. Computed on unrounded numbers.
 */
export type HoldoutScore = {
  from: string;
  to: string;
  scored: number;
  inside: number;
  mae: number;
  baseline_mae: number;
};
export type Holdout = HoldoutScore | { unavailable: HoldoutUnavailable };

type Plan = { baseline: (number | null)[] } | { unavailable: HoldoutUnavailable };

/**
 * Whether the last `horizon` days can be scored. The history before them must pass the same
 * rules as a forecast's own history, at least one of them must have a value, and every such day
 * needs a baseline value: its weekday in the last week before them, or in one of the three
 * weeks before that.
 */
export function planHoldout(
  values: (number | null)[],
  horizon: number,
  config: ForecastConfig,
): Plan {
  const training = values.length - horizon;
  if (training < config.min_history_days) return { unavailable: "SHORT_HISTORY" };
  const before = values.slice(0, training);
  if (before.filter((value) => value === null).length > before.length * config.max_missing_share)
    return { unavailable: "TOO_MANY_MISSING" };
  const outcome = values.slice(training);
  if (outcome.every((value) => value === null)) return { unavailable: "NO_OUTCOME" };
  // Last week's values repeated: each day takes its weekday from the week before the forecast,
  // or, where that day has no value, from one of the weeks before it.
  const baseline = outcome.map((value, day) => {
    if (value === null) return null;
    for (let week = 1; week <= BASELINE_WEEKS; week++) {
      const at = training - 7 * week + (day % 7);
      if (at >= 0 && before[at] != null) return before[at]!;
    }
    return undefined;
  });
  if (baseline.includes(undefined)) return { unavailable: "NO_BASELINE" };
  return { baseline: baseline as (number | null)[] };
}

export function scoreHoldout(
  values: (number | null)[],
  baseline: (number | null)[],
  predicted: Interval,
  dates: { from: string; to: string },
): HoldoutScore {
  const outcome = values.slice(values.length - baseline.length);
  let scored = 0;
  let inside = 0;
  let error = 0;
  let baselineError = 0;
  outcome.forEach((actual, day) => {
    if (actual === null) return;
    scored++;
    error += Math.abs(actual - predicted.p50[day]!);
    baselineError += Math.abs(actual - baseline[day]!);
    if (actual >= predicted.p10[day]! && actual <= predicted.p90[day]!) inside++;
  });
  return { ...dates, scored, inside, mae: error / scored, baseline_mae: baselineError / scored };
}
