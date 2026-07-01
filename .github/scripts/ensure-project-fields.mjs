#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";

const args = new Set(process.argv.slice(2));
const dryRun = args.has("--dry-run");
const selfTest = args.has("--self-test");
const owner = process.env.PROJECT_OWNER || "eneo-ai";
const projectNumber = process.env.PROJECT_NUMBER || "5";

const textAndDateFields = [
  { name: "Roadmap version", dataType: "TEXT" },
  { name: "Sponsor / municipality", dataType: "TEXT" },
  { name: "Owner / lead", dataType: "TEXT" },
  { name: "Decision needed", dataType: "TEXT" },
  { name: "Start date", dataType: "DATE" },
  { name: "Target date", dataType: "DATE" },
];

const singleSelectFields = [
  {
    name: "Status",
    options: [
      option("Todo", "GRAY", "Planned or not started"),
      option("In Progress", "BLUE", "Work has started"),
      option("Done", "GREEN", "Delivered or closed"),
    ],
  },
  {
    name: "Area",
    options: [
      option("Backend", "BLUE", "Backend service or API work"),
      option("Frontend", "GREEN", "Frontend user experience work"),
      option("Infra", "ORANGE", "Infrastructure, CI, or deployment work"),
      option("Docs", "GRAY", "Documentation work"),
      option("Security", "RED", "Security or compliance work"),
      option("Other", "GRAY", "Work that does not fit the standard areas"),
    ],
  },
  {
    name: "Priority",
    options: [
      option("P0", "RED", "Urgent or release-critical"),
      option("P1", "ORANGE", "High priority"),
      option("P2", "YELLOW", "Normal priority"),
      option("P3", "GRAY", "Low priority"),
    ],
  },
  {
    name: "Kind",
    options: [
      option("Epic", "PURPLE", "Roadmap-level outcome that can own development tasks"),
      option("Task", "BLUE", "Buildable development work item that belongs to an epic"),
      option("Bug", "RED", "Reported product defect"),
      option("Finding", "YELLOW", "Observed issue, risk, or improvement candidate before planning"),
      option("Chore", "GRAY", "Maintenance work without direct product behavior"),
    ],
  },
];

if (selfTest) {
  runSelfTest();
  process.exit(0);
}

let project = readProject(owner, projectNumber);

for (const field of textAndDateFields) {
  ensureCustomField(project, field);
  project = readProject(owner, projectNumber);
}

for (const field of singleSelectFields) {
  ensureSingleSelectField(project, field);
  project = readProject(owner, projectNumber);
}

console.log(`Project ${owner}/${projectNumber} has the required roadmap fields.`);

function option(name, color, description) {
  return { name, color, description };
}

function ensureCustomField(project, desired) {
  const existing = findField(project, desired.name);

  if (!existing) {
    runGh([
      "project",
      "field-create",
      projectNumber,
      "--owner",
      owner,
      "--name",
      desired.name,
      "--data-type",
      desired.dataType,
      "--format",
      "json",
    ], { mutates: true });
    console.log(`Created project field: ${desired.name}`);
    return;
  }

  if (existing.dataType !== desired.dataType) {
    throw new Error(
      `Project field "${desired.name}" is ${existing.dataType}, expected ${desired.dataType}. Rename or remove the conflicting field in GitHub Project ${owner}/${projectNumber}.`,
    );
  }
}

function ensureSingleSelectField(project, desired) {
  let existing = findField(project, desired.name);

  if (!existing) {
    runGh([
      "project",
      "field-create",
      projectNumber,
      "--owner",
      owner,
      "--name",
      desired.name,
      "--data-type",
      "SINGLE_SELECT",
      "--single-select-options",
      desired.options.map((option) => option.name).join(","),
      "--format",
      "json",
    ], { mutates: true });
    console.log(`Created project field: ${desired.name}`);

    if (dryRun) {
      return;
    }

    existing = findField(readProject(owner, projectNumber), desired.name);
    if (!existing) {
      throw new Error(`Created project field "${desired.name}", but GitHub did not return it on re-read.`);
    }
  }

  if (existing.dataType !== "SINGLE_SELECT") {
    throw new Error(
      `Project field "${desired.name}" is ${existing.dataType}, expected SINGLE_SELECT. Rename or remove the conflicting field in GitHub Project ${owner}/${projectNumber}.`,
    );
  }

  const nextOptions = mergeSingleSelectOptions(existing.options || [], desired.options);
  const changed = JSON.stringify(toComparableOptions(existing.options || []))
    !== JSON.stringify(toComparableOptions(nextOptions));

  if (!changed) {
    return;
  }

  runGraphql({
    query: `
      mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]) {
        updateProjectV2Field(input: { fieldId: $fieldId, singleSelectOptions: $options }) {
          projectV2Field {
            ... on ProjectV2SingleSelectField {
              id
              name
            }
          }
        }
      }
    `,
    variables: {
      fieldId: existing.id,
      options: nextOptions,
    },
  }, { mutates: true });
  console.log(`Updated project field options: ${desired.name}`);
}

function mergeSingleSelectOptions(existingOptions, desiredOptions) {
  const existingByName = new Map(
    existingOptions.map((existing) => [normalizeName(existing.name), existing]),
  );
  const desiredNames = new Set(desiredOptions.map((desired) => normalizeName(desired.name)));
  const merged = [];

  for (const desired of desiredOptions) {
    const existing = existingByName.get(normalizeName(desired.name));
    merged.push({
      ...(existing?.id ? { id: existing.id } : {}),
      name: desired.name,
      color: existing?.color || desired.color,
      description: existing?.description || desired.description,
    });
  }

  for (const existing of existingOptions) {
    if (!desiredNames.has(normalizeName(existing.name))) {
      merged.push({
        id: existing.id,
        name: existing.name,
        color: existing.color || "GRAY",
        description: existing.description || "",
      });
    }
  }

  return merged;
}

function toComparableOptions(options) {
  return options.map((option) => ({
    id: option.id || "",
    name: option.name,
    color: option.color || "",
    description: option.description || "",
  }));
}

function findField(project, name) {
  return project.fields.find((field) => field.name === name);
}

function readProject(projectOwner, number) {
  const data = runGraphql({
    query: `
      query($owner: String!, $number: Int!) {
        organization(login: $owner) {
          projectV2(number: $number) {
            id
            fields(first: 100) {
              nodes {
                __typename
                ... on ProjectV2Field {
                  id
                  name
                  dataType
                }
                ... on ProjectV2SingleSelectField {
                  id
                  name
                  dataType
                  options {
                    id
                    name
                    color
                    description
                  }
                }
                ... on ProjectV2IterationField {
                  id
                  name
                  dataType
                }
              }
            }
          }
        }
      }
    `,
    variables: {
      owner: projectOwner,
      number: Number(number),
    },
  });

  const project = data.organization?.projectV2;

  if (!project) {
    throw new Error(`GitHub Project ${projectOwner}/${number} was not found.`);
  }

  return {
    id: project.id,
    fields: project.fields.nodes.filter(Boolean),
  };
}

function runGraphql(body, options = {}) {
  const result = runGh(["api", "graphql", "--input", "-"], {
    capture: true,
    input: JSON.stringify(body),
    mutates: options.mutates,
  });
  const parsed = JSON.parse(result.stdout);

  if (parsed.errors?.length) {
    throw new Error(parsed.errors.map((error) => error.message).join("\n"));
  }

  return parsed.data;
}

function runGh(args, options = {}) {
  const printable = ["gh", ...args].join(" ");

  if (dryRun && options.mutates) {
    console.log(`[dry-run] ${printable}`);
    return { status: 0, stdout: "{}" };
  }

  let result = spawnGh("gh", args, options);

  if (result.error?.code === "ENOENT" && fs.existsSync("/opt/homebrew/bin/gh")) {
    result = spawnGh("/opt/homebrew/bin/gh", args, options);
  }

  const status = result.status ?? 1;

  if (status !== 0) {
    if (result.error) {
      process.stderr.write(`${result.error.message}\n`);
    }
    if (result.stderr) {
      process.stderr.write(result.stderr);
    }
    throw new Error(`${printable} failed with exit code ${status}`);
  }

  return {
    status,
    stdout: result.stdout || "",
  };
}

function spawnGh(command, args, options) {
  return spawnSync(command, args, {
    encoding: "utf8",
    input: options.input,
    stdio: options.capture ? ["pipe", "pipe", "pipe"] : ["pipe", "inherit", "pipe"],
    env: process.env,
  });
}

function normalizeName(value) {
  return value.trim().toLowerCase();
}

function runSelfTest() {
  const merged = mergeSingleSelectOptions(
    [
      { id: "todo-id", name: "Todo", color: "GRAY", description: "Existing todo" },
      { id: "later-id", name: "Later", color: "PINK", description: "Team-specific option" },
    ],
    [
      option("Todo", "GRAY", "Planned or not started"),
      option("In Progress", "BLUE", "Work has started"),
    ],
  );

  assert.deepEqual(merged, [
    { id: "todo-id", name: "Todo", color: "GRAY", description: "Existing todo" },
    { name: "In Progress", color: "BLUE", description: "Work has started" },
    { id: "later-id", name: "Later", color: "PINK", description: "Team-specific option" },
  ]);

  assert.equal(normalizeName(" Roadmap version "), "roadmap version");
  console.log("ensure-project-fields self-test passed");
}
