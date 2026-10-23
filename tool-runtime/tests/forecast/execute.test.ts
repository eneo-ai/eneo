import { afterAll, describe, expect, test } from "bun:test";
import ExcelJS from "exceljs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { forecastConfigSchema } from "../../src/tools/forecast/config";
import { executeForecast } from "../../src/tools/forecast/execute";
import type { HoldoutUnavailable } from "../../src/tools/forecast/evaluate";
import type { EngineRequest, ForecastEngine } from "../../src/tools/forecast/ports";

const directory = await mkdtemp(join(tmpdir(), "forecast-test-"));
afterAll(() => rm(directory, { recursive: true, force: true }));
const config = forecastConfigSchema.parse({ model_path: "/models/test" });

/** A CSV with one row per day from `start`, values from `value(day)` (null = empty cell). */
async function csv(name: string, start: string, days: number, value: (day: number) => number | null) {
  const first = Date.parse(`${start}T00:00:00Z`);
  const lines = ["Datum,kWh"];
  for (let day = 0; day < days; day++) {
    const date = new Date(first + day * 86_400_000).toISOString().slice(0, 10);
    const v = value(day);
    lines.push(`${date},${v === null ? "" : v}`);
  }
  const path = join(directory, name);
  await writeFile(path, lines.join("\n") + "\n");
  return { index: 0, path, isXlsx: false, dateColumn: "Datum", valueColumn: "kWh" };
}

/** An engine that predicts the same three levels for every day and records what it was given. */
function constantEngine(levels = { p10: 90, p50: 100, p90: 120 }) {
  const calls: EngineRequest[] = [];
  const engine: ForecastEngine = async (request) => {
    calls.push(request);
    const row = (n: number) => ({
      p10: Array(n).fill(levels.p10),
      p50: Array(n).fill(levels.p50),
      p90: Array(n).fill(levels.p90),
    });
    return {
      forecast: row(request.horizon),
      ...(request.holdout ? { holdout: row(request.horizon) } : {}),
      parameters: 28_000_000,
    };
  };
  return { engine, calls };
}

async function refusal(run: Promise<unknown>): Promise<{ code: string; message: string }> {
  try {
    await run;
  } catch (error) {
    return error as { code: string; message: string };
  }
  throw new Error("Expected the job to be refused");
}

describe("forecast job", () => {
  test("forecasts the days after the last date with the engine's interval", async () => {
    const source = await csv("daily.csv", "2026-09-01", 60, (day) => 100 + (day % 7));
    const { engine } = constantEngine();
    const result = await executeForecast({ kind: "forecast", source, horizon: 3, config }, engine);
    expect(result.forecast).toEqual({
      from: "2026-10-31",
      days: 3,
      p10: [90, 90, 90],
      p50: [100, 100, 100],
      p90: [120, 120, 120],
    });
    expect(result.history).toMatchObject({ from: "2026-09-01", to: "2026-10-30", days: 60, missing: 0 });
  });

  test("refuses missing dates and says how to give one row per day", async () => {
    const source = await csv("gap.csv", "2026-09-01", 60, (day) => 100 + day);
    const lines = (await Bun.file(source.path).text()).split("\n");
    // Drop 2026-09-11 and 2026-09-12 (rows 11 and 12 after the header).
    await writeFile(source.path, [...lines.slice(0, 11), ...lines.slice(13)].join("\n"));
    const { engine, calls } = constantEngine();
    const error = await refusal(executeForecast({ kind: "forecast", source, horizon: 3, config }, engine));
    expect(error.code).toBe("MISSING_DATES");
    expect(error.message).toContain("2026-09-11 to 2026-09-12");
    expect(error.message).toContain("one row per day");
    expect(calls).toHaveLength(0);
  });

  test("passes empty values to the engine as unknown, never as zero", async () => {
    const source = await csv("blanks.csv", "2026-08-01", 60, (day) => (day === 10 || day === 11 ? null : 50));
    const { engine, calls } = constantEngine();
    const result = await executeForecast({ kind: "forecast", source, horizon: 3, config }, engine);
    expect(result.history.missing).toBe(2);
    expect(calls[0]!.values.slice(9, 13)).toEqual([50, null, null, 50]);
  });

  describe("workbooks", () => {
    async function workbook(name: string, value: (day: number) => ExcelJS.CellValue) {
      const book = new ExcelJS.Workbook();
      const sheet = book.addWorksheet("Data");
      sheet.addRow(["Datum", "kWh", "Not"]);
      for (let day = 0; day < 40; day++)
        sheet.addRow([new Date(Date.UTC(2026, 7, 1 + day)), value(day), { formula: "1+1" }]);
      const path = join(directory, name);
      await book.xlsx.writeFile(path);
      return { index: 0, path, isXlsx: true, dateColumn: "Datum", valueColumn: "kWh" };
    }

    test("read real dates and formula results, a zero result included", async () => {
      const source = await workbook("formulas.xlsx", (day) => (day === 5 ? { formula: "1-1", result: 0 } : 10 + day));
      const { engine, calls } = constantEngine();
      const result = await executeForecast({ kind: "forecast", source, horizon: 3, config }, engine);
      expect(result.history).toMatchObject({ from: "2026-08-01", days: 40, missing: 0 });
      expect(calls[0]!.values[5]).toBe(0);
    });

    test("refuse a formula without a saved result in the forecast's columns, naming the cell", async () => {
      const source = await workbook("uncalculated.xlsx", (day) => (day === 9 ? { formula: "B2*2" } : 10 + day));
      const error = await refusal(
        executeForecast({ kind: "forecast", source, horizon: 3, config }, constantEngine().engine),
      );
      expect(error.code).toBe("UNCALCULATED_FORMULAS");
      expect(error.message).toContain("B11");
      expect(error.message).toContain("save it");
    });
  });

  describe("comparison with the outcome", () => {
    // An exact weekly pattern: 100, 110, ..., 160. Last week's same weekday is a perfect guess.
    const weekly = (day: number) => 100 + (day % 7) * 10;

    test("scores the median and the interval on the last days against last week's values", async () => {
      const source = await csv("weekly.csv", "2026-06-01", 120, weekly);
      const { engine, calls } = constantEngine({ p10: 90, p50: 100, p90: 120 });
      const result = await executeForecast({ kind: "forecast", source, horizon: 7, config }, engine);
      expect(calls[0]!.holdout).toBe(true);
      expect(result.holdout).toEqual({
        from: "2026-09-22",
        to: "2026-09-28",
        scored: 7,
        inside: 3,
        mae: 30,
        baseline_mae: 0,
      });
    });

    test("repeats the last week before the forecast for horizons longer than a week", async () => {
      const source = await csv("weekly-long.csv", "2026-06-01", 120, weekly);
      const { engine } = constantEngine({ p10: 90, p50: 100, p90: 120 });
      const result = await executeForecast({ kind: "forecast", source, horizon: 35, config }, engine);
      // Five weeks of 100..160: median errors 0..60 average 30; 100, 110 and 120 fall inside.
      expect(result.holdout).toEqual({ from: "2026-08-25", to: "2026-09-28", scored: 35, inside: 15, mae: 30, baseline_mae: 0 });
    });

    test("scores only the last days that have a value, with errors in fractions", async () => {
      // Day 117 (a 160-day) has no value; the median 100.5 misses the other six by 0.5 to 59.5.
      const source = await csv("partial.csv", "2026-06-01", 120, (d) => (d === 117 ? null : weekly(d)));
      const { engine } = constantEngine({ p10: 90, p50: 100.5, p90: 120 });
      const result = await executeForecast({ kind: "forecast", source, horizon: 7, config }, engine);
      expect(result.holdout).toMatchObject({ scored: 6, inside: 3, baseline_mae: 0 });
      expect((result.holdout as { mae: number }).mae).toBeCloseTo((9.5 + 19.5 + 29.5 + 39.5 + 0.5 + 59.5) / 6, 10);
    });

    test("takes a weekday from an earlier week when the last week lacks it", async () => {
      // Day 106 is empty: the weekday of the first last day is then read from day 99.
      const source = await csv("fallback.csv", "2026-06-01", 120, (d) => (d === 106 ? null : weekly(d)));
      const result = await executeForecast({ kind: "forecast", source, horizon: 7, config }, constantEngine().engine);
      expect(result.holdout).toMatchObject({ scored: 7, baseline_mae: 0 });
    });

    test.each([
      [
        "too many days before the last days lack a value",
        // 23 of the 90 days before the last 30 are empty (26 %); the whole history stays under 20 %.
        { start: "2026-06-01", days: 120, horizon: 30, value: (d: number) => (d >= 60 && d < 90 && d % 2 === 0 ? null : d >= 60 && d < 77 ? null : weekly(d)) },
        "TOO_MANY_MISSING",
      ],
      [
        "the history before the last days is too short",
        { start: "2026-08-01", days: 40, horizon: 30, value: weekly },
        "SHORT_HISTORY",
      ],
      [
        "a weekday has no value in the last four weeks before them",
        // The last days are 108-114; day 108's weekday falls on 80, 87, 94 and 101 in the four weeks before.
        { start: "2026-06-01", days: 115, horizon: 7, value: (d: number) => ([80, 87, 94, 101].includes(d) ? null : weekly(d)) },
        "NO_BASELINE",
      ],
    ])("is unavailable when %s", async (_case, data, reason) => {
      const source = await csv(`holdout-${reason}.csv`, data.start, data.days, data.value);
      const { engine, calls } = constantEngine();
      const result = await executeForecast({ kind: "forecast", source, horizon: data.horizon, config }, engine);
      expect(calls[0]!.holdout).toBe(false);
      expect(result.holdout).toEqual({ unavailable: reason as HoldoutUnavailable });
    });
  });

  test("starts after the last day with a value when the file's dates run on", async () => {
    // A sheet laid out for the whole period: the last 7 dates have no value yet.
    const source = await csv("planned.csv", "2026-06-01", 120, (d) => (d >= 113 ? null : 100 + (d % 7) * 10));
    const { engine, calls } = constantEngine();
    const result = await executeForecast({ kind: "forecast", source, horizon: 7, config }, engine);
    expect(calls[0]!.values).toHaveLength(113);
    expect(calls[0]!.values.at(-1)).not.toBeNull();
    expect(result.history).toMatchObject({ to: "2026-09-21", days: 113, empty_end_days: 7 });
    expect(result.forecast.from).toBe("2026-09-22");
    expect(result.holdout).toMatchObject({ scored: 7 });
  });

  test("reads a date written as midnight as that day", async () => {
    const path = join(directory, "midnight.csv");
    const lines = ["Datum,kWh"];
    for (let day = 0; day < 40; day++)
      lines.push(`${new Date(Date.UTC(2026, 7, 1 + day)).toISOString().slice(0, 10)} 00:00:00,${100 + day}`);
    await writeFile(path, lines.join("\n") + "\n");
    const source = { index: 0, path, isXlsx: false, dateColumn: "Datum", valueColumn: "kWh" };
    const result = await executeForecast({ kind: "forecast", source, horizon: 3, config }, constantEngine().engine);
    expect(result.history).toMatchObject({ from: "2026-08-01", days: 40 });
  });

  test("returns the most recent days for a chart and the size of the model", async () => {
    const plot = forecastConfigSchema.parse({ model_path: "/models/test", plot_history_days: 14 });
    const source = await csv("recent.csv", "2026-08-01", 60, (day) => (day === 55 ? null : day));
    const result = await executeForecast({ kind: "forecast", source, horizon: 3, config: plot }, constantEngine().engine);
    expect(result.recent).toEqual({
      from: "2026-09-16",
      values: [46, 47, 48, 49, 50, 51, 52, 53, 54, null, 56, 57, 58, 59],
    });
    expect(result.parameters).toBe(28_000_000);
  });

  test("refuses a history shorter than the minimum", async () => {
    const source = await csv("short.csv", "2026-10-01", 20, () => 5);
    const error = await refusal(
      executeForecast({ kind: "forecast", source, horizon: 3, config }, constantEngine().engine),
    );
    expect(error.code).toBe("SHORT_HISTORY");
    expect(error.message).toContain("20 days");
    expect(error.message).toContain("28");
  });

  test("refuses a history where too many days lack a value", async () => {
    const source = await csv("sparse.csv", "2026-08-01", 60, (day) => (day % 3 === 0 ? 7 : null));
    const error = await refusal(
      executeForecast({ kind: "forecast", source, horizon: 3, config }, constantEngine().engine),
    );
    expect(error.code).toBe("TOO_MANY_MISSING");
    // The two empty days at the end are not history; 38 of the 58 before them are empty.
    expect(error.message).toContain("38 of 58 days");
  });

  test("reads only the most recent days of a long history", async () => {
    const capped = forecastConfigSchema.parse({ model_path: "/models/test", max_history_days: 60 });
    const source = await csv("long.csv", "2026-01-01", 100, (day) => day);
    const { engine, calls } = constantEngine();
    const result = await executeForecast({ kind: "forecast", source, horizon: 3, config: capped }, engine);
    expect(calls[0]!.values).toHaveLength(60);
    expect(calls[0]!.values[0]).toBe(40);
    expect(result.history).toEqual({
      from: "2026-01-01",
      to: "2026-04-10",
      days: 100,
      missing: 0,
      used_from: "2026-02-10",
      used_days: 60,
    });
  });

  test.each([
    ["a value that is not a date", "Datum,kWh\n2026-09-01,1\nvecka 36,2\n", "INVALID_DATES", 'Row 3: "vecka 36"'],
    // A reader that guesses formats would take 1/9/2026 for one of two different days.
    ["a date that is not ISO", "Datum,kWh\n1/9/2026,1\n2/9/2026,2\n", "INVALID_DATES", 'Row 2: "1/9/2026"'],
    ["a value that is not a number", "Datum,kWh\n2026-09-01,100\n2026-09-02,#DIV/0!\n", "INVALID_VALUES", 'Row 3: "#DIV/0!"'],
    // Beyond what the model's single precision holds, a value would silently become unknown.
    ["a value too large to be a number", "Datum,kWh\n2026-09-01,100\n2026-09-02,1e309\n", "INVALID_VALUES", 'Row 3: "1e309"'],
    ["a value too large for the model", "Datum,kWh\n2026-09-01,100\n2026-09-02,1e40\n", "INVALID_VALUES", 'Row 3: "1e40"'],
    ["a time of day", "Datum,kWh\n2026-09-01 08:00:00,1\n2026-09-02 08:00:00,2\n", "INVALID_DATES", "Row 2"],
    ["dates out of order", "Datum,kWh\n2026-09-02,1\n2026-09-01,2\n", "UNORDERED_DATES", "2026-09-01"],
    ["a repeated date", "Datum,kWh\n2026-09-01,1\n2026-09-01,2\n", "UNORDERED_DATES", "2026-09-01"],
  ])("refuses %s", async (_case, text, code, detail) => {
    const path = join(directory, `bad-${code}-${detail.length}.csv`);
    await writeFile(path, text);
    const source = { index: 0, path, isXlsx: false, dateColumn: "Datum", valueColumn: "kWh" };
    const error = await refusal(
      executeForecast({ kind: "forecast", source, horizon: 3, config }, constantEngine().engine),
    );
    expect(error.code).toBe(code);
    expect(error.message).toContain(detail);
  });
});
