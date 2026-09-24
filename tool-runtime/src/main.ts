import { loadConfig } from "./config";
import { runIsolated } from "./sandbox";
import { createHandler } from "./server";
import type { ComputeOutcome } from "./tools/compute/ports";
import { computeTools } from "./tools/compute/tool";

const config = loadConfig(process.env);
// The whole-job deadline covers child start-up (Bun plus the WASM engine) on top of the
// script's own QuickJS deadline, which reports TIMEOUT as an ordinary outcome.
const jobTimeoutMs = config.compute.timeout_ms + 5_000;
const fetch = createHandler({
  token: config.token,
  maxConcurrency: config.maxConcurrency,
  toolTimeoutMs: jobTimeoutMs + 1_000,
  endpoints: [
    {
      slug: "compute",
      tools: computeTools(
        config.compute,
        async (job) =>
          (await runIsolated({ job, config: config.compute }, jobTimeoutMs)) as ComputeOutcome,
      ),
    },
  ],
});

// The token stays in this process only; sandbox children are spawned without it.
delete process.env.TOOL_RUNTIME_TOKEN;
Bun.serve({ port: config.port, fetch });
console.log(JSON.stringify({ event: "listening", port: config.port }));
