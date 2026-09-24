// Sandbox child entrypoint: reads one job from stdin, writes one JSON message to stdout, exits.
import { publicError } from "./errors";
import type { ComputeConfig } from "./tools/compute/config";
import type { ComputeJob } from "./tools/compute/ports";

export type SandboxJob = { job: ComputeJob; config: ComputeConfig } | { job: { kind: "env" } };

async function execute(input: SandboxJob): Promise<Record<string, unknown>> {
  switch (input.job.kind) {
    case "compute": {
      // Imported lazily so the engine is loaded only inside children.
      const { runJavaScript } = await import("./tools/compute/engine/quickjs");
      const { config } = input as Extract<SandboxJob, { config: ComputeConfig }>;
      return { ...(await runJavaScript(input.job, config)) };
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
  process.exit(0);
}
