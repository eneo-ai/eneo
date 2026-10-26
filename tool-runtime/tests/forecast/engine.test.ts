import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { chmod, copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { engineResult, forecastAvailable, forecastReady, timestralEngine } from "../../src/tools/forecast/engine/timestral";
import { tinyCheckpoint } from "./checkpoint";

const directory = await mkdtemp(join(tmpdir(), "forecast-engine-test-"));
afterAll(() => rm(directory, { recursive: true, force: true }));

const daily = (days: number) =>
  Array.from({ length: days }, (_, day) => 100 + 30 * Math.sin((2 * Math.PI * day) / 7));

// Bun still runs a skipped describe's body, so nothing in it may need the sidecar.
describe.skipIf(!(await forecastAvailable()))("the Timestral engine", () => {
  let modelPath = "";
  let engine: ReturnType<typeof timestralEngine>;
  beforeAll(async () => {
    modelPath = await tinyCheckpoint(directory);
    engine = timestralEngine({ modelPath, threads: 1 });
  });

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
    const refused = await missing({ values: daily(60), horizon: 3, holdout: false }).catch((error) => error);
    expect(refused).toMatchObject({ code: "MODEL_UNAVAILABLE" });
    // The message reaches the model and the user: what is missing, never where.
    expect(refused.message).not.toContain(directory);
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
    const refused = await spoiled({ values: daily(60), horizon: 3, holdout: false }).catch((error) => error);
    expect(refused).toMatchObject({ code: "MODEL_UNAVAILABLE" });
    expect(refused.message).not.toContain(path);
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

describe("the sidecar's answer", () => {
  const days = (n: number) => Array.from({ length: n }, (_, i) => 100 + i);
  const interval = (n: number) => ({ p10: days(n), p50: days(n), p90: days(n) });
  const answer = (fields: Record<string, unknown> = {}) =>
    JSON.stringify({ forecast: interval(3), parameters: 28_000_000, ...fields });

  test("is read when it has a finite value for each day asked for", () => {
    expect(engineResult(answer(), 3, false).forecast.p50).toEqual([100, 101, 102]);
    expect(engineResult(answer({ holdout: interval(3) }), 3, true).holdout).toEqual(interval(3));
  });

  test.each([
    ["output that is not JSON", "Traceback (most recent call last)", false],
    ["a day too few", answer({ forecast: { ...interval(3), p90: days(2) } }), false],
    ["a value that is not a number", answer({ forecast: { ...interval(3), p50: [100, null, 102] } }), false],
    ["no check when one was asked for", answer(), true],
    ["no size of the model", JSON.stringify({ forecast: interval(3) }), false],
  ])("refuses %s as a failed model", (_case, stdout, holdout) => {
    expect(() => engineResult(stdout, 3, holdout)).toThrow(expect.objectContaining({ code: "ENGINE_FAILED" }));
  });
});

describe("whether a forecast can run", () => {
  // Stand-ins for the sidecar and a mounted checkpoint: readiness looks for the files only.
  async function install(parts: { python?: boolean; script?: boolean; config?: boolean; weights?: boolean }) {
    const root = await mkdtemp(join(directory, "ready-"));
    const model = join(root, "model");
    await mkdir(model);
    const write = async (on: boolean | undefined, path: string) => on !== false && writeFile(path, "");
    await write(parts.python, join(root, "python"));
    await write(parts.script, join(root, "forecast.py"));
    await write(parts.config, join(model, "config.json"));
    await write(parts.weights, join(model, "model.safetensors"));
    return forecastReady(model, join(root, "python"), join(root, "forecast.py"));
  }

  test("needs the sidecar's Python and script and both checkpoint files", async () => {
    expect(await install({})).toBe(true);
    expect(await install({ python: false })).toBe(false);
    expect(await install({ script: false })).toBe(false);
    expect(await install({ config: false })).toBe(false);
    expect(await install({ weights: false })).toBe(false);
  });
});
