import { loadConfig } from "./config";
import { concurrencyLimit, runIsolated } from "./sandbox";
import { createHandler, type Endpoint } from "./server";
import type { ComputeOutcome } from "./tools/compute/ports";
import { computeTools } from "./tools/compute/tool";
import { defaultCacheRoot, SheetCache } from "./tools/tabular/cache";
import type { QueryJobResult, SheetMetadata } from "./tools/tabular/ports";
import { tabularTools } from "./tools/tabular/tool";
import type { RenderResult } from "./tools/documents/ports";
import { documentTools, fileRenderer, spreadsheetTools } from "./tools/documents/tool";
import { chartConfigSchema } from "./tools/charts/config";
import type { ChartRendering } from "./tools/charts/ports";
import { chartTools } from "./tools/charts/tool";

const config = loadConfig(process.env);
// The whole-job deadline covers child start-up (Bun plus the WASM engine) on top of the
// script's own QuickJS deadline, which reports TIMEOUT as an ordinary outcome.
const computeJobTimeoutMs = config.compute.timeout_ms + 5_000;
const endpoints: Endpoint[] = [
  {
    slug: "compute",
    toolTimeoutMs: computeJobTimeoutMs + 1_000,
    tools: computeTools(
      config.compute,
      async (job) =>
        (await runIsolated({ job, config: config.compute }, computeJobTimeoutMs)) as ComputeOutcome,
    ),
  },
];
const tabular = config.tabular.config;
const slot = concurrencyLimit(config.tabular.concurrency);
// Budgets keep one call (downloads, a parse, a query) inside Eneo's 60 s tool-call timeout.
const ingestTimeoutMs = 25_000;
const queryJobTimeoutMs = Math.min(tabular.query_timeout_ms + 10_000, 30_000);
endpoints.push({
  slug: "tabular",
  requiresIdentity: true,
  toolTimeoutMs: 55_000,
  tools: tabularTools({
    config: tabular,
    allowedFileOrigins: config.tabular.allowedFileOrigins,
    cache: new SheetCache(defaultCacheRoot(), tabular.cache_ttl_ms, tabular.cache_max_bytes),
    executor: {
      ingest: (job) =>
        slot(
          async () => (await runIsolated({ job }, ingestTimeoutMs)) as { sheets: SheetMetadata[] },
        ),
      query: (job) =>
        slot(
          async () => (await runIsolated({ job }, queryJobTimeoutMs)) as unknown as QueryJobResult,
        ),
    },
  }),
});

// Rendering shares the native-job slots: a large workbook or PDF is as heavy as a query.
const renderTimeoutMs = 25_000;
const render = fileRenderer((job) =>
  slot(async () => (await runIsolated({ job }, renderTimeoutMs)) as RenderResult),
);
endpoints.push(
  {
    slug: "documents",
    toolTimeoutMs: renderTimeoutMs + 5_000,
    tools: documentTools(config.documents, render),
  },
  {
    slug: "spreadsheets",
    toolTimeoutMs: renderTimeoutMs + 5_000,
    tools: spreadsheetTools(config.documents, render, {
      allowedFileOrigins: config.tabular.allowedFileOrigins,
      maxBytes: tabular.max_upload_bytes,
      timeoutMs: tabular.download_timeout_ms,
    }),
  },
  {
    slug: "charts",
    toolTimeoutMs: renderTimeoutMs + 5_000,
    tools: chartTools(
      chartConfigSchema.parse({}),
      (job) => slot(async () => (await runIsolated({ job }, renderTimeoutMs)) as ChartRendering),
      {
        allowedFileOrigins: config.tabular.allowedFileOrigins,
        maxBytes: tabular.max_upload_bytes,
        timeoutMs: tabular.download_timeout_ms,
      },
    ),
  },
);

const fetch = createHandler({
  token: config.token,
  maxConcurrency: config.maxConcurrency,
  endpoints,
});

// The token stays in this process only; sandbox children are spawned without it.
delete process.env.TOOL_RUNTIME_TOKEN;
Bun.serve({ port: config.port, fetch });
console.log(
  JSON.stringify({
    event: "listening",
    port: config.port,
    endpoints: endpoints.map((e) => e.slug),
  }),
);
