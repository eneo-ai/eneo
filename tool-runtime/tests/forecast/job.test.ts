import { afterAll, describe, expect, test } from "bun:test";
import { mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
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

/** Processes whose command line names `path`: from /proc on Linux, from ps elsewhere. */
async function running(path: string): Promise<number[]> {
  if (process.platform === "linux") {
    const pids: number[] = [];
    for (const entry of await readdir("/proc")) {
      if (!/^\d+$/.test(entry)) continue;
      const command = await Bun.file(`/proc/${entry}/cmdline`).text().catch(() => "");
      if (command.split("\0").includes(path)) pids.push(Number(entry));
    }
    return pids;
  }
  const listing = Bun.spawnSync(["ps", "-axo", "pid=,args="]).stdout.toString();
  return listing
    .split("\n")
    .filter((line) => line.includes(path) && !line.includes("ps -axo"))
    .map((line) => Number(line.trim().split(/\s+/)[0]));
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

  test("leaves no sidecar behind when the call is cancelled", async () => {
    // A stand-in sidecar that waits far past the cancellation. It is a Bun script because a
    // confined child may start Bun and the forecast Python, nothing else (no /bin/sh).
    const fake = join(directory, "fake-python");
    await writeFile(fake, `#!${process.execPath}\nawait Bun.sleep(60_000);\n`, { mode: 0o755 });
    const previous = process.env.FORECAST_PYTHON;
    process.env.FORECAST_PYTHON = fake;
    try {
      const controller = new AbortController();
      const run = runIsolated({ job: await job(directory) }, 30_000, { signal: controller.signal });
      // A job that fails before the sidecar starts must fail the test, not leave it waiting.
      let settled: unknown;
      run.catch((error) => (settled = error));
      let pids: number[] = [];
      while (!(pids = await running(fake)).length) {
        if (settled) throw settled;
        await Bun.sleep(50);
      }
      controller.abort();
      await expect(run).rejects.toMatchObject({ code: "CANCELLED" });
      await Bun.sleep(100);
      expect(await running(fake)).toEqual([]);
    } finally {
      if (previous === undefined) delete process.env.FORECAST_PYTHON;
      else process.env.FORECAST_PYTHON = previous;
    }
  });

  test("reports a missing model as unavailable, not as a crash", async () => {
    const forecast = await job(join(directory, "no-model-here"));
    await expect(runIsolated({ job: forecast }, 30_000)).rejects.toMatchObject({
      code: "MODEL_UNAVAILABLE",
    });
  });
});
