import { afterAll, describe, expect, test } from "bun:test";
import { chmod, copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { forecastAvailable, timestralEngine } from "../../src/tools/forecast/engine/timestral";
import { tinyCheckpoint } from "./checkpoint";

const directory = await mkdtemp(join(tmpdir(), "forecast-engine-test-"));
afterAll(() => rm(directory, { recursive: true, force: true }));

const daily = (days: number) =>
  Array.from({ length: days }, (_, day) => 100 + 30 * Math.sin((2 * Math.PI * day) / 7));

describe.skipIf(!(await forecastAvailable()))("the Timestral engine", async () => {
  const modelPath = await tinyCheckpoint(directory);
  const engine = timestralEngine({ modelPath, threads: 1 });

  test("returns P10 <= P50 <= P90 for every day of the horizon, and the model's size", async () => {
    const result = await engine({ values: daily(90), horizon: 14, holdout: false });
    expect(result.forecast.p50).toHaveLength(14);
    for (let day = 0; day < 14; day++) {
      expect(result.forecast.p10[day]!).toBeLessThanOrEqual(result.forecast.p50[day]!);
      expect(result.forecast.p50[day]!).toBeLessThanOrEqual(result.forecast.p90[day]!);
    }
    expect(result.holdout).toBeUndefined();
    expect(result.parameters).toBeGreaterThan(1000);
  });

  test("forecasts the last days without seeing them", async () => {
    const values: (number | null)[] = daily(90);
    values[40] = null;
    const first = await engine({ values, horizon: 7, holdout: true });
    const changed = [...values.slice(0, 83), ...values.slice(83).map((v) => (v ?? 0) * 3)];
    const second = await engine({ values: changed, horizon: 7, holdout: true });
    expect(second.holdout).toEqual(first.holdout!);
    expect(second.forecast).not.toEqual(first.forecast);
  });

  test("refuses a missing checkpoint without looking anywhere else for it", async () => {
    const missing = timestralEngine({ modelPath: join(directory, "mistralai/Timestral-28M"), threads: 1 });
    await expect(missing({ values: daily(60), horizon: 3, holdout: false })).rejects.toMatchObject({
      code: "MODEL_UNAVAILABLE",
    });
  });

  test.each([
    ["weights that are not a safetensors file", async (path: string) => writeFile(join(path, "model.safetensors"), "not weights")],
    ["weights it may not read", async (path: string) => chmod(join(path, "model.safetensors"), 0o000)],
  ])("refuses a Timestral config with %s", async (_case, spoil) => {
    // Permissions do not stop root (a container's test run): only the decoding case applies.
    if (_case.includes("may not read") && process.getuid?.() === 0) return;
    const path = join(directory, `spoiled-${_case.length}`);
    await mkdir(path, { recursive: true });
    await copyFile(join(modelPath, "config.json"), join(path, "config.json"));
    await copyFile(join(modelPath, "model.safetensors"), join(path, "model.safetensors"));
    await spoil(path);
    const spoiled = timestralEngine({ modelPath: path, threads: 1 });
    await expect(spoiled({ values: daily(60), horizon: 3, holdout: false })).rejects.toMatchObject({
      code: "MODEL_UNAVAILABLE",
    });
    await chmod(join(path, "model.safetensors"), 0o600);
  });

  test("refuses a directory that is not a Timestral checkpoint", async () => {
    const path = join(directory, "other");
    await Bun.write(join(path, "config.json"), JSON.stringify({ model_type: "something-else" }));
    await writeFile(join(path, "model.safetensors"), "not weights");
    const other = timestralEngine({ modelPath: path, threads: 1 });
    await expect(other({ values: daily(60), horizon: 3, holdout: false })).rejects.toMatchObject({
      code: "MODEL_UNAVAILABLE",
    });
  });
});
