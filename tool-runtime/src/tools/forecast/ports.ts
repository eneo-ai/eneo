import type { SheetSource } from "../documents/ports";
import type { ForecastConfig } from "./config";
import type { Holdout } from "./evaluate";

/** The two columns of a CSV or XLSX file a forecast reads: one row per day. */
export type ForecastSource = SheetSource & { dateColumn: string; valueColumn: string };

/** Child job: read one daily series from `source` and forecast `horizon` days after it. */
export type ForecastJob = {
  kind: "forecast";
  source: ForecastSource;
  horizon: number;
  config: ForecastConfig;
};

/** Three levels of a quantile forecast, one value per day. */
export type Interval = { p10: number[]; p50: number[]; p90: number[] };

/**
 * What the model is given: validated numbers only, never dates, file names or paths of the
 * user's data. `null` is a day without a value. With `holdout` the engine also forecasts the
 * last `horizon` days from the history before them, for the comparison with the outcome.
 */
export type EngineRequest = { values: (number | null)[]; horizon: number; holdout: boolean };
export type EngineResult = { forecast: Interval; holdout?: Interval; parameters: number };
export type ForecastEngine = (request: EngineRequest) => Promise<EngineResult>;

/** A forecast of `days` days from `from`, each with its interval. */
export type ForecastDays = { from: string; days: number } & Interval;

export type ForecastResult = {
  /** The file's days; when longer than the model reads, the window it read starts `used_from`. */
  history: {
    /** Dates at the end of the file without a value; the forecast starts before them. */
    empty_end_days?: number;
    from: string;
    to: string;
    days: number;
    /** Days without a value in the window the model read. */
    missing: number;
    used_from?: string;
    used_days?: number;
  };
  forecast: ForecastDays;
  recent: { from: string; values: (number | null)[] };
  holdout: Holdout;
  /** The size of the model that made the forecast. */
  parameters: number;
};
