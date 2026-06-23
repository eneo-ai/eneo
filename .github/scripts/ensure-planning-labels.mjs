#!/usr/bin/env node

import { spawnSync } from "node:child_process";

const dryRun = process.argv.includes("--dry-run");
const repo = process.env.GITHUB_REPOSITORY || "eneo-ai/eneo";

const labels = [
  {
    name: "kind:epic",
    color: "5319e7",
    description: "Roadmap-level planning item that can own development tasks",
  },
  {
    name: "kind:task",
    color: "1d76db",
    description: "Buildable development work item that should belong to an epic",
  },
  {
    name: "kind:finding",
    color: "d4c5f9",
    description: "Observed issue, risk, or improvement candidate before planning",
  },
  {
    name: "kind:chore",
    color: "cfd3d7",
    description: "Maintenance work without direct product behavior",
  },
  {
    name: "needs:epic",
    color: "fbca04",
    description: "Development task needs a linked parent epic before it is ready",
  },
  {
    name: "needs:triage",
    color: "fef2c0",
    description: "Needs product or engineering triage before planning",
  },
];

const existingLabels = listExistingLabels();

function runGh(args, options = {}) {
  const printable = ["gh", ...args].join(" ");

  if (dryRun) {
    console.log(`[dry-run] ${printable}`);
    return { status: 0, stdout: "" };
  }

  const result = spawnSync("gh", args, {
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    env: process.env,
  });

  return {
    status: result.status ?? 1,
    stdout: result.stdout || "",
  };
}

for (const label of labels) {
  const command = existingLabels.has(label.name.toLowerCase()) ? "edit" : "create";
  const result = runGh([
    "label",
    command,
    label.name,
    "--repo",
    repo,
    "--color",
    label.color,
    "--description",
    label.description,
  ]);

  if (result.status !== 0) {
    process.exit(result.status);
  }
}

function listExistingLabels() {
  const result = runGh([
    "label",
    "list",
    "--repo",
    repo,
    "--limit",
    "500",
    "--json",
    "name",
    "--jq",
    ".[].name",
  ], {
    capture: true,
  });

  if (result.status !== 0) {
    return new Set();
  }

  return new Set(
    result.stdout
      .split("\n")
      .map((name) => name.trim().toLowerCase())
      .filter(Boolean),
  );
}
