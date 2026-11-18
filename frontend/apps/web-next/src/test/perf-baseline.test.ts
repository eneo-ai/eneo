import { readdirSync, readFileSync } from "node:fs";
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
const RETIRED_NEXT_VERSION = "16.4.1";

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

it("preserves the baseline for the retired Next version", () => {
  expect(files).toContain(`baseline-next-${RETIRED_NEXT_VERSION}.json`);
});

it.each(files)("perf/%s has complete samples and a stable consecutive run", (file) => {
  const baseline = JSON.parse(readFileSync(path.join(PERF, file), "utf8")) as Baseline;
  const stability = JSON.parse(
    readFileSync(path.join(PERF, file.replace("baseline-", "stability-")), "utf8")
  ) as PerfRun;
  expect(`baseline-next-${baseline.meta.frameworkVersion}.json`).toBe(file);
  for (const report of [baseline, stability]) {
    // The historical comparison stays fixed when the active app changes.
    expect(report.meta).toMatchObject({
      framework: "next",
      frameworkVersion: RETIRED_NEXT_VERSION,
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
