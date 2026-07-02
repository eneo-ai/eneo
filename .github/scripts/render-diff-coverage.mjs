#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

if (process.argv.includes("--self-test")) {
  runSelfTest();
  process.exit(0);
}

const frontendPath = getArgValue("--frontend") || "fe.json";
const backendPath = getArgValue("--backend") || "be.json";
const outputPath = getArgValue("--output") || "diff-coverage.md";
const summaryPath = getArgValue("--summary") || process.env.GITHUB_STEP_SUMMARY;

const body = renderReport([
  ["Frontend", load(frontendPath)],
  ["Backend", load(backendPath)],
]);

fs.writeFileSync(outputPath, body);

if (summaryPath) {
  fs.appendFileSync(summaryPath, body);
}

function renderReport(entries) {
  const areas = entries.filter(([, data]) => data && (data.total_num_lines || 0) > 0);
  const rows = [];
  const details = [];

  for (const [label, data] of areas) {
    const total = data.total_num_lines || 0;
    const miss = data.total_num_violations || 0;
    const pct = Math.round(data.total_percent_covered || 0);

    rows.push(`| ${label} | ${total} | ${miss} | ${pct}% |`);

    const files = Object.entries(data.src_stats || {})
      .map(([file, stats]) => [file, stats.violation_lines || []])
      .filter(([, violationLines]) => violationLines.length)
      .map(([file, violationLines]) => `- \`${shorten(file)}\` - ${ranges(violationLines)}`);

    if (files.length) {
      details.push([label, files]);
    }
  }

  let body = [
    "<!-- diff-coverage-report -->",
    "## Patch coverage",
    "",
    "Share of this PR's new or changed lines exercised by tests. Report-only; never gates the PR.",
    "",
  ].join("\n");

  if (rows.length) {
    body += [
      "| Area | Changed | Uncovered | Coverage |",
      "| --- | ---: | ---: | ---: |",
      rows.join("\n"),
      "",
    ].join("\n");
  } else {
    body += "_No changed lines with coverage data in this PR._\n";
  }

  for (const [label, files] of details) {
    const count = files.length;
    body += [
      "",
      `<details><summary>Uncovered lines: ${label} (${count} file${count === 1 ? "" : "s"})</summary>`,
      "",
      files.join("\n"),
      "",
      "</details>",
      "",
    ].join("\n");
  }

  return body.endsWith("\n") ? body : `${body}\n`;
}

function load(path) {
  try {
    return JSON.parse(fs.readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function shorten(path) {
  const segments = path.split("/");
  return segments.length > 3 ? `.../${segments.slice(-3).join("/")}` : path;
}

function ranges(values) {
  const sorted = [...new Set(values)].sort((a, b) => a - b);
  const out = [];
  let start = null;
  let previous = null;

  for (const value of sorted) {
    if (start === null) {
      start = value;
      previous = value;
    } else if (value === previous + 1) {
      previous = value;
    } else {
      out.push([start, previous]);
      start = value;
      previous = value;
    }
  }

  if (start !== null) {
    out.push([start, previous]);
  }

  return out.map(([first, last]) => (first === last ? `${first}` : `${first}-${last}`)).join(", ");
}

function getArgValue(name) {
  const index = process.argv.indexOf(name);

  if (index === -1) {
    return null;
  }

  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) {
    throw new Error(`${name} requires a value`);
  }

  return value;
}

function runSelfTest() {
  assert.equal(
    renderReport([
      ["Frontend", null],
      ["Backend", null],
    ]).includes("No changed lines with coverage data"),
    true,
  );

  const report = renderReport([
    [
      "Backend",
      {
        total_num_lines: 4,
        total_num_violations: 2,
        total_percent_covered: 50,
        src_stats: {
          "backend/src/eneo/example.py": {
            violation_lines: [10, 11, 14],
          },
        },
      },
    ],
  ]);

  assert.equal(report.includes("| Backend | 4 | 2 | 50% |"), true);
  assert.equal(report.includes("`.../src/eneo/example.py` - 10-11, 14"), true);

  console.log("render-diff-coverage self-test passed");
}
