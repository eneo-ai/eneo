import { describe, expect, mock, test } from "bun:test";
import { createHandler } from "../../src/server";
import { forecastConfigSchema } from "../../src/tools/forecast/config";
import type { ForecastJob, ForecastResult } from "../../src/tools/forecast/ports";
import { forecastTools } from "../../src/tools/forecast/tool";
import { RichResult, type CallContext } from "../../src/tools/types";

const ORIGIN = "https://eneo.example";
const url = `${ORIGIN}/api/v1/files/00000000-0000-4000-8000-000000000001/original/download/?token=t`;
const ctx: CallContext = { tenantId: "", userId: "", fileOrigin: ORIGIN };
const config = forecastConfigSchema.parse({ model_path: "/models/forecast", model_name: "Timestral 28M" });
const source = { url, filename: "el.xlsx", sheet: "Data" };
const columns = { date_column: "Datum", value_column: "kWh" };

function outcome(horizon: number, recentDays = 3): ForecastResult {
  const days = (n: number, value: number) => Array.from({ length: n }, (_, i) => value + i + 0.123456789);
  return {
    history: { from: "2026-01-01", to: "2026-03-31", days: 90, missing: 1 },
    forecast: { from: "2026-04-01", days: horizon, p10: days(horizon, 1600), p50: days(horizon, 1834), p90: days(horizon, 2100) },
    recent: { from: "2026-03-29", values: [...days(recentDays - 1, 1700), null] },
    holdout: { from: "2026-03-25", to: "2026-03-31", scored: 7, inside: 6, mae: 96.4567, baseline_mae: 138.0123 },
    parameters: 28_000_000,
  };
}

function setup(result: ForecastResult) {
  const run = mock(async (_job: ForecastJob) => result);
  const download = mock(async () => ({ bytes: Buffer.from("Datum,kWh\n"), contentType: "text/csv", name: "el" }));
  const tool = forecastTools(config, run, { allowedFileOrigins: [], maxBytes: 1_000_000, timeoutMs: 1000, download: download as never })[0]!;
  return { tool, run, download };
}

describe("create_forecast", () => {
  function rpc(tool: ReturnType<typeof setup>["tool"], method: string, params: unknown) {
    const handler = createHandler({ token: "forecast-test", maxConcurrency: 1, endpoints: [{ slug: "forecast", tools: [tool], toolTimeoutMs: 1000 }] });
    return handler(
      new Request("http://runtime/mcp/forecast", {
        method: "POST",
        headers: {
          authorization: "Bearer forecast-test",
          "content-type": "application/json",
          accept: "application/json, text/event-stream",
          "x-eneo-file-origin": ORIGIN,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
      }),
    ).then((response) => response.json() as Promise<{ result: any }>);
  }

  test("advertises one daily date column, one value column and the horizon limit", async () => {
    const { tool } = setup(outcome(3));
    const { result } = await rpc(tool, "tools/list", {});
    const listed = result.tools[0]! as { name: string; description: string; inputSchema: any };
    expect(listed.name).toBe("create_forecast");
    // The columns sit beside the horizon, where a model writes them; the source is only the file.
    expect(listed.inputSchema.required).toEqual(expect.arrayContaining(["source", "date_column", "value_column", "horizon"]));
    expect(Object.keys(listed.inputSchema.properties.source.properties)).toEqual(["url", "filename", "sheet"]);
    expect(listed.inputSchema.properties.horizon.maximum).toBe(180);
    expect(listed.description).toContain("one row per day");
    expect(listed.description).toContain("query_table");
    expect(listed.description).toContain("Never add P10 or P90");
    // The forecast starts after the last value, not after the file's last date.
    expect(listed.description).toContain("the day after the last day with a value");
    expect(listed.inputSchema.properties.horizon.description).toContain("after the last day with a value");
  });

  test("runs a call that also repeats the columns in the source", async () => {
    const { tool, run } = setup(outcome(3));
    const { result } = await rpc(tool, "tools/call", {
      name: "create_forecast",
      arguments: { source: { ...source, ...columns }, ...columns, horizon: 3 },
    });
    expect(result.isError).toBeFalsy();
    expect(run.mock.calls[0]![0].source).toMatchObject({ dateColumn: "Datum", valueColumn: "kWh" });
  });

  test("returns the forecast rounded for reading, with the model that made it", async () => {
    const { tool, run } = setup(outcome(3));
    const result = (await tool.execute({ source, ...columns, horizon: 3, title: "El, 3 dagar" }, ctx)) as Record<string, any>;
    expect(run.mock.calls[0]![0]).toMatchObject({
      kind: "forecast",
      horizon: 3,
      source: { isXlsx: true, sheet: "Data", dateColumn: "Datum", valueColumn: "kWh" },
    });
    expect(result.forecast).toEqual({ from: "2026-04-01", days: 3, p10: [1600, 1601, 1602], p50: [1834, 1835, 1836], p90: [2100, 2101, 2102] });
    expect(result.recent).toEqual({ from: "2026-03-29", values: [1700, 1701, null] });
    expect(result.holdout).toEqual({ from: "2026-03-25", to: "2026-03-31", scored: 7, inside: 6, mae: 96.46, baseline_mae: 138 });
    expect(result.model).toEqual({ name: "Timestral 28M", parameters: 28_000_000 });
    expect(result.title).toBe("El, 3 dagar");
    expect(result.interval).toContain("each day on its own");
  });

  test("says in words why the check against the last days is unavailable", async () => {
    const { tool } = setup({ ...outcome(3), holdout: { unavailable: "NO_OUTCOME" } });
    const result = (await tool.execute({ source, ...columns, horizon: 3 }, ctx)) as Record<string, any>;
    expect(result.holdout).toEqual({
      unavailable: "NO_OUTCOME",
      reason: "None of the last days has a value to compare with.",
    });
  });

  test("exports the history as the file holds it and the forecast at the model's precision", async () => {
    const f32 = Math.fround;
    const result = outcome(2);
    result.recent = { from: "2026-03-30", values: [123456789, null] };
    result.forecast = { ...result.forecast, p10: [f32(1.2345678806304932), f32(1020.89496)], p50: [f32(1834.567), f32(1835)], p90: [f32(2100.25), f32(2101)] };
    const { tool } = setup(result);
    const exported = await tool.execute({ source, ...columns, horizon: 2, export: true }, ctx);
    expect(exported).toBeInstanceOf(RichResult);
    const file = (exported as RichResult).files[0]!;
    expect(file.mimeType).toBe("text/csv");
    expect(file.uri).toEndWith("/prognos.csv");
    expect(Buffer.from(file.blob, "base64").toString()).toBe(
      "date,actual,p10,p50,p90\r\n" +
        "2026-03-30,123456789,,,\r\n" +
        "2026-03-31,,,,\r\n" +
        "2026-04-01,,1.2345679,1834.567,2100.25\r\n" +
        // Some single-precision values need nine digits to read back.
        "2026-04-02,,1020.89496,1835,2101\r\n",
    );
    // Each forecast value reads back as the same single-precision number the model returned.
    expect(f32(1.2345679)).toBe(f32(1.2345678806304932));
  });

  test("refuses a horizon beyond the limit before downloading anything", async () => {
    const { tool, download, run } = setup(outcome(3));
    await expect(tool.execute({ source, ...columns, horizon: 181 }, ctx)).rejects.toThrow();
    expect(download).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });

  test("keeps the longest result well inside the model's text budget", async () => {
    const { tool } = setup(outcome(180, 180));
    const result = await tool.execute({ source, ...columns, horizon: 180 }, ctx);
    expect(JSON.stringify(result).length).toBeLessThan(16_000);
  });
});
