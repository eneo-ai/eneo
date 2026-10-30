import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { expect, it } from "vitest";
import {
  CHAT_ROUTE,
  compareRuns,
  summarize,
  type Metrics,
  type Samples
} from "../../tests/perf/metrics";

// Phase 4 and phase 6 compare against these committed reports. Raw samples
// preserve the evidence behind the summaries and the two-run stability check.
const PERF = path.resolve(import.meta.dirname, "../../perf");
const ROUTES = [CHAT_ROUTE, "/spaces/list", "/admin/users", "/admin/insights"];
const PAGE_METRICS = [
  "coldLcpMs",
  "coldCls",
  "warmLcpMs",
  "warmCls",
  "htmlEncodedBytes",
  "htmlDecodedBytes"
];
const CHAT_METRICS = [
  "coldChatReadyMs",
  "warmChatReadyMs",
  "navigationToSpacesListMs",
  "chatTtftMs",
  "inpMs"
];
const installedNext = (createRequire(import.meta.url)("next/package.json") as { version: string })
  .version;

type PerfRun = {
  meta: {
    commit: string;
    framework: string;
    frameworkVersion: string;
    node: string;
    os: string;
    cpu: string;
    date: string;
    runs: number;
  };
  metrics: Metrics;
  samples: Samples;
};
type Baseline = PerfRun & {
  build: { coldSeconds: number; warmSeconds: number; peakRssMb: number };
};

const files = readdirSync(PERF).filter((file) => /^baseline-next-.*\.json$/.test(file));

it("has a baseline for the installed Next version", () => {
  expect(files).toContain(`baseline-next-${installedNext}.json`);
});

it.each(files)("perf/%s has complete samples and a stable consecutive run", (file) => {
  const baseline = JSON.parse(readFileSync(path.join(PERF, file), "utf8")) as Baseline;
  const stability = JSON.parse(
    readFileSync(path.join(PERF, file.replace("baseline-", "stability-")), "utf8")
  ) as PerfRun;
  expect(`baseline-next-${baseline.meta.frameworkVersion}.json`).toBe(file);
  for (const report of [baseline, stability]) {
    // Reject stale locally installed Next versions as well as incomplete runs.
    expect(report.meta).toMatchObject({
      framework: "next",
      frameworkVersion: installedNext,
      node: "v22.23.4",
      runs: 30
    });
    for (const route of ROUTES) {
      const metrics = route === CHAT_ROUTE ? [...PAGE_METRICS, ...CHAT_METRICS] : PAGE_METRICS;
      for (const metric of metrics) {
        const values = report.samples[route]?.[metric];
        expect(values, `${route} ${metric}`).toHaveLength(report.meta.runs);
        expect(values?.every(Number.isFinite), `${route} ${metric}`).toBe(true);
      }
    }
    expect(report.metrics).toEqual(summarize(report.samples));
  }
  for (const key of ["commit", "node", "os", "cpu"] as const) {
    expect(baseline.meta[key]).not.toBe("");
    expect(stability.meta[key]).toBe(baseline.meta[key]);
  }
  expect(
    compareRuns(baseline.metrics, stability.metrics).filter((row) => row.stable === false)
  ).toEqual([]);
  for (const value of [
    baseline.build.coldSeconds,
    baseline.build.warmSeconds,
    baseline.build.peakRssMb
  ]) {
    expect(Number.isFinite(value)).toBe(true);
    expect(value).toBeGreaterThan(0);
  }
});
