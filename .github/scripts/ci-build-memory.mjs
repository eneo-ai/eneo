#!/usr/bin/env node

import fs from "node:fs";
import { pathToFileURL } from "node:url";

// Peak memory of the Svelte production build, from GNU time's -v report.
export function readPeakRssMb(report) {
  const kb = Number(report.match(/^\s*Maximum resident set size \(kbytes\): (\d+)\s*$/m)?.[1]);
  if (!Number.isFinite(kb) || kb <= 0) throw new Error("no peak memory in the build measurement");
  return kb / 1024;
}

// The budget sits below the Node heap limit, so growth fails the PR that
// causes it instead of surfacing later as a random out-of-memory crash.
export function checkBuildMemory(peakMb, budgetMb) {
  if (!Number.isFinite(budgetMb) || budgetMb <= 0) throw new Error("invalid memory budget");
  const gb = (mb) => `${(mb / 1024).toFixed(2)} GB`;
  const summary = `Svelte production build: peak ${gb(peakMb)} of a ${gb(budgetMb)} budget`;
  return { ok: peakMb <= budgetMb, summary };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const peak = readPeakRssMb(fs.readFileSync(process.argv[2], "utf8"));
    const { ok, summary } = checkBuildMemory(peak, Number(process.env.BUILD_MEMORY_BUDGET_MB));
    if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
    if (ok) console.log(summary);
    else {
      console.error(`::error::${summary}. Find what grew the build before raising the budget.`);
      process.exitCode = 1;
    }
  } catch (error) {
    console.error(`::error::Cannot check build memory: ${error.message}`);
    process.exitCode = 1;
  }
}
