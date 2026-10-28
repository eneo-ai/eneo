import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { expect, it } from "vitest";

// The phase 4 and phase 6 gates compare against the committed Next baseline
// (perf/, written by tests/perf/baseline.perf.ts). It only counts when it was
// measured on the Next version the lockfile installs, with every metric.

const PERF = path.resolve(import.meta.dirname, "../../perf");
const ROUTES = ["/spaces/personal/chat", "/spaces/list", "/admin/users", "/admin/insights"];
const PAGE_METRICS = [
  "coldLcpMs",
  "coldCls",
  "warmLcpMs",
  "warmCls",
  "htmlEncodedBytes",
  "htmlDecodedBytes"
];
const CHAT_METRICS = ["navigationToSpacesListMs", "chatTtftMs", "inpMs"];
const installedNext = (createRequire(import.meta.url)("next/package.json") as { version: string })
  .version;

type Baseline = {
  meta: { framework: string; frameworkVersion: string; runs: number };
  metrics: Record<string, Record<string, { median: number; p75: number }>>;
  build: { coldSeconds: number; warmSeconds: number; peakRssMb: number };
};

const files = readdirSync(PERF).filter((file) => /^baseline-next-.*\.json$/.test(file));

it("has a baseline for the installed Next version", () => {
  expect(files).toContain(`baseline-next-${installedNext}.json`);
});

it.each(files)(
  "perf/%s was measured on the Next version in its name, with every metric",
  (file) => {
    const baseline = JSON.parse(readFileSync(path.join(PERF, file), "utf8")) as Baseline;
    expect(baseline.meta.framework).toBe("next");
    expect(`baseline-next-${baseline.meta.frameworkVersion}.json`).toBe(file);
    // A baseline from another Next version (for example a stale local 16.3.8) is rejected.
    expect(baseline.meta.frameworkVersion).toBe(installedNext);
    expect(baseline.meta.runs).toBeGreaterThanOrEqual(5);
    for (const route of ROUTES) {
      const metrics = route === ROUTES[0] ? [...PAGE_METRICS, ...CHAT_METRICS] : PAGE_METRICS;
      for (const metric of metrics) {
        expect(baseline.metrics[route]?.[metric]?.median, `${route} ${metric}`).toEqual(
          expect.any(Number)
        );
      }
    }
    expect(baseline.build.peakRssMb).toBeGreaterThan(0);
  }
);
