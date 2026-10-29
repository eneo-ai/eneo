// Runs inside sandbox children only. Timestral runs as a Python sidecar the runtime image
// installs (scripts/forecast.py in a venv); the child spawns it inside its own confinement, with
// the child's private directory as the only place it may write and the checkpoint as the only
// model it may read. It gets validated numbers in and quantiles out, nothing of the user's file.
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { ToolError } from "../../../errors";
import type { EngineResult, ForecastEngine } from "../ports";

/** The Python with torch and timestral; the image installs it here, a developer may point elsewhere. */
export const FORECAST_PYTHON = process.env.FORECAST_PYTHON ?? "/opt/forecast/bin/python3";
const SCRIPT = fileURLToPath(new URL("../../../../scripts/forecast.py", import.meta.url));
const SIDECAR_TIMEOUT_MS = 25_000;
const MAX_STDERR = 2_000;
/** The script's exit status for a refusal it explains on stdout. */
const REFUSED = 3;

/** Whether the sidecar is installed; tests skip engine cases without it. */
export async function forecastAvailable(): Promise<boolean> {
  return (await Bun.file(FORECAST_PYTHON).exists()) && (await Bun.file(SCRIPT).exists());
}

export function timestralEngine(options: { modelPath: string; threads: number }): ForecastEngine {
  return async (request) => {
    if (!(await forecastAvailable()))
      throw new ToolError(
        "MODEL_UNAVAILABLE",
        "Forecasting is not installed on this runtime (Python sidecar).",
      );
    const directory = await mkdtemp(join(process.env.TMPDIR ?? tmpdir(), "eneo-forecast-"));
    const jobPath = join(directory, "job.json");
    await writeFile(
      jobPath,
      JSON.stringify({ ...request, model_path: options.modelPath, threads: options.threads }),
      { mode: 0o600 },
    );
    const threads = String(options.threads);
    const child = Bun.spawn([FORECAST_PYTHON, "-I", "-B", SCRIPT, jobPath], {
      cwd: directory,
      env: {
        HOME: directory,
        TMPDIR: directory,
        // The thread pools of torch's BLAS back ends size themselves from these at start-up.
        OMP_NUM_THREADS: threads,
        MKL_NUM_THREADS: threads,
        OPENBLAS_NUM_THREADS: threads,
        // Never fetch a model: the checkpoint is the directory the operator mounted.
        HF_HUB_OFFLINE: "1",
        HF_HUB_DISABLE_TELEMETRY: "1",
        LANG: "C.UTF-8",
        LC_ALL: "C.UTF-8",
      },
      stdin: "ignore",
      stdout: "pipe",
      stderr: "pipe",
    });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, SIDECAR_TIMEOUT_MS);
    try {
      const [stdout, stderr, code] = await Promise.all([
        new Response(child.stdout).text(),
        new Response(child.stderr).text(),
        child.exited,
      ]);
      if (timedOut)
        throw new ToolError(
          "TIMEOUT",
          `The forecast model did not finish within ${SIDECAR_TIMEOUT_MS / 1000} seconds.`,
        );
      if (code === REFUSED) {
        const refusal = refusalSchema.safeParse(json(stdout));
        if (refusal.success) throw new ToolError(refusal.data.error.code, refusal.data.error.message);
      }
      if (code !== 0) {
        const detail = stderr.trim().split("\n").filter(Boolean).at(-1)?.slice(0, MAX_STDERR);
        throw new ToolError(
          "ENGINE_FAILED",
          `The forecast model failed${detail ? `: ${detail}` : ""}.`,
        );
      }
      return engineResult(stdout, request.horizon, request.holdout);
    } finally {
      clearTimeout(timer);
    }
  };
}

const refusalSchema = z.object({ error: z.object({ code: z.string().max(64), message: z.string().max(1000) }) });

function json(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** The sidecar's answer, checked: a day for each day asked for, finite numbers only. */
export function engineResult(stdout: string, horizon: number, holdout: boolean): EngineResult {
  const days = z.array(z.number().finite()).length(horizon);
  const interval = z.object({ p10: days, p50: days, p90: days });
  const parsed = z
    .object({ forecast: interval, holdout: interval.optional(), parameters: z.number().int().positive() })
    .safeParse(json(stdout));
  if (!parsed.success || (holdout && parsed.data.holdout === undefined))
    throw new ToolError("ENGINE_FAILED", "The forecast model returned an answer that could not be read.");
  return parsed.data as EngineResult;
}
