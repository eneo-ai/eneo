// Runs inside sandbox children only: reads the daily series and asks the engine for a forecast.
import { ToolError } from "../../errors";
import { readSource } from "../documents/sources";
import { planHoldout, scoreHoldout } from "./evaluate";
import type {
  EngineResult,
  ForecastEngine,
  ForecastJob,
  ForecastResult,
  Interval,
} from "./ports";
import { DAY_MS, dailySeries, isoDay } from "./series";

export async function executeForecast(
  job: ForecastJob,
  engine: ForecastEngine,
): Promise<ForecastResult> {
  // As text: dates and numbers are validated here, not guessed by the reader.
  const { columns, rows } = await readSource(job.source, { asText: true });
  const series = dailySeries(
    rows,
    column(columns, job.source.dateColumn),
    column(columns, job.source.valueColumn),
  );
  const { config } = job;
  const days = series.values.length;
  if (days < config.min_history_days)
    throw new ToolError(
      "SHORT_HISTORY",
      `The file covers ${days} days; a forecast needs at least ${config.min_history_days} days of history.`,
    );
  // The model reads the most recent days only; missing values are counted where it reads.
  const values = series.values.slice(-config.max_history_days);
  const missing = values.filter((value) => value === null).length;
  if (missing > values.length * config.max_missing_share)
    throw new ToolError(
      "TOO_MANY_MISSING",
      `${missing} of ${values.length} days have no value; at most ${Math.round(config.max_missing_share * 100)}% may be missing. ` +
        "Choose a period or a column with fewer gaps.",
    );
  const plan = planHoldout(values, job.horizon, config);
  const prediction = await engine({
    values,
    horizon: job.horizon,
    holdout: "baseline" in plan,
  });
  const start = Date.parse(`${series.from}T00:00:00Z`);
  const capped = values.length < days;
  const day = (index: number) => isoDay(start + index * DAY_MS);
  return {
    history: {
      from: series.from,
      to: isoDay(start + (days - 1) * DAY_MS),
      days,
      missing,
      ...(capped
        ? { used_from: isoDay(start + (days - values.length) * DAY_MS), used_days: values.length }
        : {}),
    },
    forecast: { from: day(days), days: job.horizon, ...prediction.forecast },
    // What a chart shows before the forecast: the most recent days, gaps kept as gaps.
    recent: {
      from: day(days - Math.min(values.length, config.plot_history_days)),
      values: values.slice(-config.plot_history_days),
    },
    holdout:
      "baseline" in plan
        ? scoreHoldout(values, plan.baseline, holdoutOf(prediction), {
            from: day(days - job.horizon),
            to: day(days - 1),
          })
        : plan,
    parameters: prediction.parameters,
  };
}

function holdoutOf(prediction: EngineResult): Interval {
  if (!prediction.holdout)
    throw new ToolError("ENGINE_FAILED", "The forecast model returned no comparison forecast.");
  return prediction.holdout;
}

function column(columns: string[], name: string): number {
  const at = columns.indexOf(name);
  if (at < 0)
    throw new ToolError(
      "UNKNOWN_COLUMN",
      `The source has no column "${name}". Columns: ${columns.join(", ")}.`,
    );
  return at;
}
