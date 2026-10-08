// Sandbox child entrypoint: reads one job from stdin, writes one JSON message to stdout, exits.
import { readdirSync } from "node:fs";
import { dirname } from "node:path";
import { publicError, ToolError } from "./errors";
import type { ComputeConfig } from "./tools/compute/config";
import type { ComputeJob } from "./tools/compute/ports";
import type { IngestJob, QueryJob } from "./tools/tabular/ports";
import type { RenderJob } from "./tools/documents/ports";
import type { ChartJob } from "./tools/charts/ports";

export type SandboxJob =
  | { job: ComputeJob; config: ComputeConfig }
  | { job: IngestJob }
  | { job: QueryJob }
  | { job: RenderJob }
  | { job: ChartJob }
  | { job: { kind: "env" } }
  | { job: { kind: "confinement" } };

/** Argument that makes the child refuse its job unless it finds itself confined. */
export const REQUIRE_CONFINEMENT = "--require-confinement";

async function execute(input: SandboxJob): Promise<Record<string, unknown>> {
  // Engines are imported lazily so each one loads only inside the children that use it.
  switch (input.job.kind) {
    case "compute": {
      const { runJavaScript } = await import("./tools/compute/engine/quickjs");
      const { config } = input as Extract<SandboxJob, { config: ComputeConfig }>;
      return { ...(await runJavaScript(input.job, config)) };
    }
    case "tabular_ingest": {
      const { executeIngest } = await import("./tools/tabular/execute");
      return executeIngest(input.job);
    }
    case "tabular_query": {
      const { executeQuery } = await import("./tools/tabular/execute");
      return executeQuery(input.job);
    }
    case "render_document": {
      const { executeRender } = await import("./tools/documents/execute");
      return executeRender(input.job);
    }
    case "render_chart": {
      const { executeChart } = await import("./tools/charts/execute");
      return { ...(await executeChart(input.job)) };
    }
    case "env":
      // Test probe: the variable names the child inherited, never their values.
      return { names: Object.keys(process.env).sort() };
    case "confinement":
      // Start-up probe: what the launcher actually enforces on a child of this runtime.
      return { files: filesConfined(), tcp: tcpConfined() };
  }
}

/**
 * Whether this process is confined to its own files. Tested, not assumed: the directory above
 * its private one holds every job's directory, and a confined child may not list it.
 */
function filesConfined(): boolean {
  const own = process.env.TMPDIR;
  if (!own) return false;
  try {
    readdirSync(dirname(own));
    return false;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EACCES";
  }
}

/** Whether TCP is denied: a confined child cannot even bind a loopback port. */
function tcpConfined(): boolean {
  try {
    Bun.listen({ hostname: "127.0.0.1", port: 0, socket: { data() {} } }).stop(true);
    return false;
  } catch {
    return true;
  }
}

if (import.meta.main) {
  try {
    if (process.argv.includes(REQUIRE_CONFINEMENT) && !filesConfined())
      throw new ToolError(
        "CONFINEMENT_UNAVAILABLE",
        "This runtime requires confined jobs, but this host cannot confine them.",
      );
    const input = JSON.parse(await Bun.stdin.text()) as SandboxJob;
    const result = await execute(input);
    process.stdout.write(JSON.stringify({ ok: true, result }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: publicError(error) }));
  }
  // Native engine resources (DuckDB) must never extend the lifetime of a job.
  process.exit(0);
}
