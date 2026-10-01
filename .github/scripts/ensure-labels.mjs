#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { LABELS } from "./label-policy.mjs";

const dryRun = process.argv.includes("--dry-run");
const repo = process.env.GITHUB_REPOSITORY || "eneo-ai/eneo";

function runGh(args) {
  const result = spawnSync("gh", args, {
    encoding: "utf8", timeout: 60_000, maxBuffer: 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message || result.stderr.trim());
  }
  return result.stdout;
}

// A failed read must not be treated as an empty repository. Do not recreate
// labels or overwrite metadata when GitHub could not be queried.
const existing = new Map(JSON.parse(runGh([
  "label", "list", "--repo", repo, "--limit", "500", "--json", "name,color,description",
])).map((label) => [label.name.toLowerCase(), label]));

for (const label of LABELS) {
  const current = existing.get(label.name);
  if (current?.color.toLowerCase() === label.color && current.description === label.description) continue;
  const args = [
    "label", current ? "edit" : "create", label.name, "--repo", repo,
    "--color", label.color, "--description", label.description,
  ];
  if (dryRun) console.log(`[dry-run] ${current ? "Update" : "Create"} ${label.name}: ${label.description}`);
  else {
    runGh(args);
    console.log(`${current ? "Updated" : "Created"} ${label.name}`);
  }
}
