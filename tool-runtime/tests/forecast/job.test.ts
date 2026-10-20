import { afterAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { jobPaths, runIsolated } from "../../src/sandbox";
import { forecastConfigSchema } from "../../src/tools/forecast/config";
import { forecastAvailable } from "../../src/tools/forecast/engine/timestral";
import type { ForecastJob } from "../../src/tools/forecast/ports";
import { tinyCheckpoint } from "./checkpoint";

const directory = await mkdtemp(join(tmpdir(), "forecast-job-test-"));
const available = await forecastAvailable();
afterAll(() => rm(directory, { recursive: true, force: true }));

async function job(modelPath: string): Promise<ForecastJob> {
  const sourceDir = await mkdtemp(join(directory, "source-"));
  const path = join(sourceDir, "source-0");
  const lines = ["Datum,Besök"];
  for (let day = 0; day < 70; day++)
    lines.push(`${new Date(Date.UTC(2026, 6, 1 + day)).toISOString().slice(0, 10)},${40 + (day % 7) * 5}`);
  await writeFile(path, lines.join("\n") + "\n");
  return {
    kind: "forecast",
    source: { index: 0, path, isXlsx: false, dateColumn: "Datum", valueColumn: "Besök" },
    horizon: 7,
    config: forecastConfigSchema.parse({ model_path: modelPath, threads: 1 }),
  };
}

describe("forecast job in a sandbox child", () => {
  test("may read only its checkpoint and write only next to its source", async () => {
    const forecast = await job("/models/forecast");
    expect(jobPaths(forecast)).toEqual({
      read: ["/models/forecast"],
      write: [dirname(forecast.source.path!)],
    });
  });

  test.skipIf(!available)("forecasts from a file in a fresh process", async () => {
    const forecast = await job(await tinyCheckpoint(directory));
    const result = await runIsolated({ job: forecast }, 30_000);
    expect(result).toMatchObject({
      history: { from: "2026-07-01", to: "2026-09-08", days: 70, missing: 0 },
      forecast: { from: "2026-09-09", days: 7 },
      holdout: { from: "2026-09-02", to: "2026-09-08", scored: 7 },
    });
  });

  test("reports a missing model as unavailable, not as a crash", async () => {
    const forecast = await job(join(directory, "no-model-here"));
    await expect(runIsolated({ job: forecast }, 30_000)).rejects.toMatchObject({
      code: "MODEL_UNAVAILABLE",
    });
  });
});
