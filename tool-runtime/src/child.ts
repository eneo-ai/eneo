// Sandbox child entrypoint: reads one job from stdin, writes one JSON message to stdout, exits.
import { publicError } from "./errors";
import type { ComputeConfig } from "./tools/compute/config";
import type { ComputeJob } from "./tools/compute/ports";
import type { IngestJob, QueryJob } from "./tools/tabular/ports";
import type { RenderJob } from "./tools/documents/ports";

export type SandboxJob =
  | { job: ComputeJob; config: ComputeConfig }
  | { job: IngestJob }
  | { job: QueryJob }
  | { job: RenderJob }
  | { job: { kind: "env" } };

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
    case "env":
      // Test probe: the variable names the child inherited, never their values.
      return { names: Object.keys(process.env).sort() };
  }
}

if (import.meta.main) {
  try {
    const input = JSON.parse(await Bun.stdin.text()) as SandboxJob;
    const result = await execute(input);
    process.stdout.write(JSON.stringify({ ok: true, result }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: publicError(error) }));
  }
  // Native engine resources (DuckDB) must never extend the lifetime of a job.
  process.exit(0);
}
