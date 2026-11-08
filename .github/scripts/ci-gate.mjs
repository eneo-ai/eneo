#!/usr/bin/env node

import { pathToFileURL } from "node:url";

// The scope job owns which jobs are required. The gate owns the lifecycle
// contract: required means success, and only excluded jobs may be skipped.
export function evaluateCi(expected, needs) {
  if (!expected || Array.isArray(expected) || typeof expected !== "object"
      || !needs || Array.isArray(needs) || typeof needs !== "object") {
    throw new Error("CI scope and job results must be objects");
  }
  const errors = [];
  for (const job of ["changes", "security"]) {
    if (expected[job] !== true) errors.push(`${job} must always be required`);
  }
  for (const job of new Set([...Object.keys(expected), ...Object.keys(needs)])) {
    const required = expected[job];
    const result = needs[job]?.result;
    if (typeof required !== "boolean") {
      errors.push(`${job}: missing or invalid scope decision`);
    } else if (result !== "success" && !(required === false && result === "skipped")) {
      errors.push(`${job}: ${result || "missing"}; expected ${required ? "success" : "success or skipped"}`);
    }
  }
  return errors;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const errors = evaluateCi(JSON.parse(process.env.EXPECTED_JOBS), JSON.parse(process.env.JOB_RESULTS));
    for (const error of errors) console.error(`::error::${error}`);
    if (errors.length) process.exitCode = 1;
    else console.log("Every required CI job succeeded; only excluded jobs were skipped.");
  } catch (error) {
    console.error(`::error::Cannot verify CI results: ${error.message}`);
    process.exitCode = 1;
  }
}
