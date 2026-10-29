import { afterAll, describe, expect, test } from "bun:test";
import { realpathSync } from "node:fs";
import { mkdir, mkdtemp, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { confinement, jobPaths, runIsolated } from "../../src/sandbox";
import { forecastConfigSchema } from "../../src/tools/forecast/config";
import { FORECAST_PYTHON, forecastAvailable } from "../../src/tools/forecast/engine/timestral";
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

/** The parent of a process: from /proc on Linux, from ps elsewhere. */
async function parentOf(pid: number): Promise<number> {
  if (process.platform === "linux") {
    const stat = await Bun.file(`/proc/${pid}/stat`).text();
    return Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]);
  }
  return Number(Bun.spawnSync(["ps", "-o", "ppid=", "-p", String(pid)]).stdout.toString().trim());
}

/**
 * Processes running `path`: as the program, or as the script its interpreter runs (a stand-in
 * sidecar is a Bun script). A launcher that only names the path among its arguments, such as
 * landrun granting it, is not one of them. From /proc on Linux, from ps elsewhere.
 */
async function running(path: string): Promise<number[]> {
  const runs = (args: string[]) => args[0] === path || args[1] === path;
  if (process.platform === "linux") {
    const pids: number[] = [];
    for (const entry of await readdir("/proc")) {
      if (!/^\d+$/.test(entry)) continue;
      const command = await Bun.file(`/proc/${entry}/cmdline`).text().catch(() => "");
      if (runs(command.split("\0"))) pids.push(Number(entry));
    }
    return pids;
  }
  const listing = Bun.spawnSync(["ps", "-axo", "pid=,args="]).stdout.toString();
  return listing
    .split("\n")
    .map((line) => line.trim().split(/\s+/))
    .filter(([, ...args]) => runs(args))
    .map(([pid]) => Number(pid));
}

describe("forecast job in a sandbox child", () => {
  test("may read only its checkpoint and write only next to its source", async () => {
    const forecast = await job("/models/forecast");
    const paths = jobPaths(forecast);
    expect(paths).toMatchObject({ read: ["/models/forecast"], write: [dirname(forecast.source.path!)] });
    // Only a forecast job may run the sidecar's Python; a compute job may not.
    expect(paths.execute).toContain(dirname(dirname(process.env.FORECAST_PYTHON ?? "/opt/forecast/bin/python3")));
    expect(jobPaths({ kind: "compute", code: "1", input: null } as never).execute).toBeUndefined();
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

  /**
   * A stand-in sidecar that waits far past any deadline: a venv whose python is the forecast
   * interpreter itself, with a .pth file that sleeps before any script runs (site runs it for the
   * venv's site-packages even in isolated mode; a sitecustomize would lose to Debian's own in the
   * standard library). The child starts it exactly as it starts the real sidecar, under the same
   * rules: its venv and the interpreter, nothing around them.
   */
  async function standIn(name: string): Promise<string> {
    const real = realpathSync(FORECAST_PYTHON);
    const version = Bun.spawnSync([real, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]).stdout.toString().trim();
    const venv = join(directory, name, "venv");
    const python = join(venv, "bin", "python");
    await mkdir(join(venv, "bin"), { recursive: true });
    await mkdir(join(venv, "lib", `python${version}`, "site-packages"), { recursive: true });
    await writeFile(join(venv, "pyvenv.cfg"), `home = ${dirname(real)}\ninclude-system-site-packages = false\n`);
    await writeFile(join(venv, "lib", `python${version}`, "site-packages", "stand-in.pth"), "import time; time.sleep(60)\n");
    await symlink(real, python);
    return python;
  }

  /** Runs a forecast job with `python` as the sidecar until the sidecar is up. */
  async function startWith(python: string, signal?: AbortSignal) {
    const previous = process.env.FORECAST_PYTHON;
    process.env.FORECAST_PYTHON = python;
    const forecast = await job(directory);
    // Where landrun is installed, the child must actually be confined for this to count.
    const requireConfinement = confinement({ job: forecast }, directory).length > 0;
    const run = runIsolated({ job: forecast }, 30_000, { signal, requireConfinement });
    const restore = () => {
      if (previous === undefined) delete process.env.FORECAST_PYTHON;
      else process.env.FORECAST_PYTHON = previous;
    };
    // A job that fails before the sidecar starts must fail the test, not leave it waiting.
    let settled: unknown;
    run.catch((error) => (settled = error));
    let pids: number[] = [];
    while (!(pids = await running(python)).length) {
      if (settled) {
        restore();
        throw settled;
      }
      await Bun.sleep(50);
    }
    return { run, sidecar: pids[0]!, restore };
  }

  test.skipIf(!available)("leaves no sidecar behind when the call is cancelled", async () => {
    const python = await standIn("cancelled");
    const controller = new AbortController();
    const { run, restore } = await startWith(python, controller.signal);
    try {
      controller.abort();
      await expect(run).rejects.toMatchObject({ code: "CANCELLED" });
      await Bun.sleep(100);
      expect(await running(python)).toEqual([]);
    } finally {
      restore();
    }
  });

  test.skipIf(!available)("leaves no sidecar behind when the job process dies under it", async () => {
    const python = await standIn("crashed");
    const { run, sidecar, restore } = await startWith(python);
    try {
      // Only the Bun job that started the sidecar is killed, as an out-of-memory kill would.
      process.kill(await parentOf(sidecar), "SIGKILL");
      await expect(run).rejects.toMatchObject({ code: "SANDBOX_CRASH" });
      await Bun.sleep(100);
      expect(await running(python)).toEqual([]);
    } finally {
      restore();
    }
  });

  test("reports a missing model as unavailable, not as a crash", async () => {
    const forecast = await job(join(directory, "no-model-here"));
    await expect(runIsolated({ job: forecast }, 30_000)).rejects.toMatchObject({
      code: "MODEL_UNAVAILABLE",
    });
  });
});
