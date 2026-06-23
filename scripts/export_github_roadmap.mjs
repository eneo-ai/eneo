#!/usr/bin/env node

import fs from "node:fs";
import { spawnSync } from "node:child_process";

const args = parseArgs(process.argv.slice(2));
const owner = args.owner || process.env.PROJECT_OWNER || "eneo-ai";
const project = args.project || process.env.PROJECT_NUMBER || "5";
const limit = args.limit || "1000";
const format = args.format || "markdown";

const data = args.input
  ? readInput(args.input)
  : readProjectItems({ owner, project, limit });

const epics = (data.items || [])
  .filter(isEpic)
  .map(toEpic)
  .sort(compareEpics);

const output = format === "mermaid"
  ? renderMermaid(epics)
  : renderMarkdown(epics, { owner, project });

if (args.output) {
  fs.writeFileSync(args.output, output);
} else {
  process.stdout.write(output);
}

function readProjectItems({ owner, project, limit }) {
  const result = spawnSync("gh", [
    "project",
    "item-list",
    project,
    "--owner",
    owner,
    "--limit",
    limit,
    "--format",
    "json",
  ], {
    encoding: "utf8",
    env: process.env,
  });

  if (result.status !== 0) {
    process.stderr.write(result.stderr || "Failed to read GitHub Project items.\n");
    process.exit(result.status ?? 1);
  }

  return JSON.parse(result.stdout);
}

function readInput(path) {
  const source = path === "-" ? fs.readFileSync(0, "utf8") : fs.readFileSync(path, "utf8");
  return JSON.parse(source);
}

function isEpic(item) {
  const kind = getField(item, ["kind"]);
  const labels = getLabels(item);
  const title = getTitle(item);
  const body = item.content?.body || "";

  return equals(kind, "Epic")
    || labels.some((label) => equals(label, "kind:epic"))
    || /^\[epic\]/i.test(title)
    || Boolean(getSectionValue(body, ["Roadmap version"]));
}

function toEpic(item, index) {
  const body = item.content?.body || "";
  const version = firstValue([
    getField(item, ["roadmap version", "version", "target version", "quarter"]),
    getSectionValue(body, ["Roadmap version", "Target version", "Version", "Quarter"]),
    "Unscheduled",
  ]);

  return {
    id: item.id || `epic-${index}`,
    number: item.content?.number,
    title: getTitle(item),
    url: item.content?.url,
    status: firstValue([getField(item, ["status"]), "Todo"]),
    priority: firstValue([
      getField(item, ["priority"]),
      getSectionValue(body, ["Priority"]),
      "",
    ]),
    area: firstValue([
      getField(item, ["area"]),
      getSectionValue(body, ["Area"]),
      "",
    ]),
    version,
  };
}

function renderMarkdown(epics, context) {
  return [
    "# Eneo roadmap",
    "",
    `Generated from GitHub Project ${context.owner}/${context.project}.`,
    "",
    "```mermaid",
    renderMermaid(epics),
    "```",
    "",
    ...renderVersionSections(epics),
  ].join("\n");
}

function renderMermaid(epics) {
  if (epics.length === 0) {
    return [
      "flowchart LR",
      "  empty[\"No epics found\"]",
    ].join("\n");
  }

  const versions = [...new Set(epics.map((epic) => epic.version))].sort(compareVersions);
  const lines = [
    "flowchart LR",
    "  classDef version fill:#f6f8fa,stroke:#57606a,color:#24292f,font-weight:bold",
    "  classDef epic fill:#ddf4ff,stroke:#0969da,color:#24292f",
  ];

  for (const version of versions) {
    lines.push(`  ${versionNodeId(version)}["${escapeMermaid(version)}"]:::version`);
  }

  for (const epic of epics) {
    const label = epic.number ? `#${epic.number} ${epic.title}` : epic.title;
    lines.push(`  ${epicNodeId(epic)}["${escapeMermaid(label)}"]:::epic`);
    lines.push(`  ${versionNodeId(epic.version)} --> ${epicNodeId(epic)}`);
  }

  return lines.join("\n");
}

function renderVersionSections(epics) {
  const versions = [...new Set(epics.map((epic) => epic.version))].sort(compareVersions);
  const lines = [];

  for (const version of versions) {
    lines.push(`## ${version}`);
    lines.push("");

    for (const epic of epics.filter((candidate) => candidate.version === version)) {
      const title = epic.url
        ? `[${escapeMarkdown(epic.title)}](${epic.url})`
        : escapeMarkdown(epic.title);
      const prefix = epic.number ? `#${epic.number} ` : "";
      const meta = [epic.status, epic.priority, epic.area].filter(Boolean).join(" / ");
      lines.push(`- ${prefix}${title}${meta ? ` - ${escapeMarkdown(meta)}` : ""}`);
    }

    lines.push("");
  }

  return lines;
}

function getField(item, names) {
  for (const [key, value] of Object.entries(item)) {
    if (names.some((name) => key.toLowerCase() === name.toLowerCase())) {
      return normalizeValue(value);
    }
  }

  return "";
}

function getSectionValue(body, headings) {
  for (const heading of headings) {
    const escaped = escapeRegExp(heading);
    const pattern = new RegExp(
      `^#{2,6}\\s+${escaped}\\s*$([\\s\\S]*?)(?=^#{2,6}\\s+|$(?![\\s\\S]))`,
      "im",
    );
    const match = body.match(pattern);

    if (!match) {
      continue;
    }

    const value = match[1]
      .replace(/<!--[\s\S]*?-->/g, "")
      .trim()
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)[0];

    if (value) {
      return value;
    }
  }

  return "";
}

function getLabels(item) {
  return (item.labels || []).map((label) => {
    if (typeof label === "string") {
      return label;
    }

    return label.name || "";
  }).filter(Boolean);
}

function getTitle(item) {
  return item.title || item.content?.title || "Untitled epic";
}

function firstValue(values) {
  return values.map(normalizeValue).find(Boolean) || "";
}

function normalizeValue(value) {
  if (value === null || value === undefined) {
    return "";
  }

  if (Array.isArray(value)) {
    return value.map(normalizeValue).filter(Boolean).join(", ");
  }

  if (typeof value === "object") {
    return value.name || value.title || "";
  }

  return String(value).trim();
}

function compareEpics(left, right) {
  return compareVersions(left.version, right.version)
    || comparePriority(left.priority, right.priority)
    || left.title.localeCompare(right.title);
}

function compareVersions(left, right) {
  const leftRank = versionRank(left);
  const rightRank = versionRank(right);

  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }

  return left.localeCompare(right);
}

function versionRank(version) {
  const normalized = version.toLowerCase();

  if (normalized === "unscheduled") {
    return 10_000;
  }

  if (normalized === "future") {
    return 9_000;
  }

  const match = /^v?(\d+)(?:\.(\d+))?/.exec(normalized);

  if (!match) {
    return 8_000;
  }

  return Number(match[1]) * 100 + Number(match[2] || 0);
}

function comparePriority(left, right) {
  return priorityRank(left) - priorityRank(right);
}

function priorityRank(priority) {
  const match = /^p(\d)$/i.exec(priority || "");
  return match ? Number(match[1]) : 99;
}

function equals(left, right) {
  return String(left || "").toLowerCase() === String(right || "").toLowerCase();
}

function versionNodeId(version) {
  return `version_${slug(version)}`;
}

function epicNodeId(epic) {
  return `epic_${epic.number || slug(epic.id)}`;
}

function slug(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "unknown";
}

function escapeMermaid(value) {
  return String(value).replace(/"/g, "'");
}

function escapeMarkdown(value) {
  return String(value).replace(/\|/g, "\\|");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseArgs(argv) {
  const parsed = {};

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (!arg.startsWith("--")) {
      continue;
    }

    const key = arg.slice(2);
    const next = argv[index + 1];

    if (!next || next.startsWith("--")) {
      parsed[key] = "true";
      continue;
    }

    parsed[key] = next;
    index += 1;
  }

  return parsed;
}
