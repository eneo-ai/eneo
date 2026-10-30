#!/usr/bin/env node

import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

const outputNames = [
  "full",
  "backend",
  "frontend",
  "frontend_e2e",
  "schema",
  "scripts",
  "route_metadata",
  "docker_backend",
  "docker_frontend",
  "docker_devcontainer",
  "web_next",
  "web_next_e2e",
  "docker_web_next",
];

const dockerImages = [
  { image: "backend", context: "./backend", file: "./backend/Dockerfile" },
  { image: "frontend", context: "./frontend", file: "./frontend/Dockerfile" },
  { image: "web-next", context: "./frontend", file: "./frontend/apps/web-next/Dockerfile" },
  { image: "devcontainer", context: "./.devcontainer", file: "./.devcontainer/Dockerfile" },
];

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const eventName = process.env.GITHUB_EVENT_NAME || "pull_request";
  let files = [];
  try {
    if (process.argv.includes("--github-event")) {
      const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
      const base = eventName === "pull_request"
        ? event.pull_request?.base?.sha : event.merge_group?.base_sha;
      if (["pull_request", "merge_group"].includes(eventName)) {
        files = changedFiles(base, process.env.GITHUB_SHA);
      }
    } else {
      const filesPath = getArgValue("--files");
      files = filesPath ? fs.readFileSync(filesPath, "utf8").split("\n") : process.argv.slice(2);
    }
  } catch (error) {
    console.error(`::warning::Cannot determine changed files; running full CI. ${error.message}`);
  }
  const plan = planCi(files, eventName);
  writeOutputs(plan);
  if (process.env.GITHUB_STEP_SUMMARY) {
    const jobs = Object.entries(plan.expected_jobs).filter(([, required]) => required).map(([job]) => job);
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY,
      `## CI scope\n\nEvent: \`${eventName}\`; ${plan.full ? "full validation" : `${files.length} changed paths`}.\n\n`
      + `Required jobs: ${jobs.map((job) => `\`${job}\``).join(", ")}.\n\n`
      + `Docker images: ${plan.docker_matrix.include.map(({ image }) => image).join(", ") || "none"}.\n`);
  }
}

export function changedFiles(base, head, cwd = process.cwd()) {
  // Never substitute HEAD^: a queue candidate can include several PRs.
  if (![base, head].every((sha) => typeof sha === "string" && /^[0-9a-f]{40}$/.test(sha))) {
    throw new Error("A valid base and head SHA are required for scoped CI");
  }
  return execFileSync("git", ["diff", "--no-renames", "--name-only", "-z", base, head, "--"], {
    cwd, encoding: "utf8", timeout: 30_000, maxBuffer: 4 * 1024 * 1024,
  }).split("\0").filter(Boolean);
}

export function planCi(files, eventName) {
  // Reusable workflows inherit the caller's event. Pushes, tags and manual
  // publication always validate everything, even when their diff is narrow.
  const scope = ["pull_request", "merge_group"].includes(eventName) ? classify(files) : allTrue();
  const images = dockerImages.filter(({ image }) => scope[`docker_${image.replaceAll("-", "_")}`]);
  return {
    ...scope,
    docker: images.length > 0,
    docker_matrix: { include: images },
    expected_jobs: {
      changes: true,
      security: true,
      "user-facing": eventName === "pull_request",
      "backend-quality": scope.backend,
      "backend-tests": scope.backend,
      frontend: scope.frontend,
      "frontend-e2e": scope.frontend_e2e,
      "frontend-web-next": scope.web_next,
      "frontend-web-next-e2e": scope.web_next_e2e,
      "schema-drift": scope.schema,
      "docker-builds": images.length > 0,
    },
  };
}

export function classify(rawFiles) {
  const files = normalizeFiles(rawFiles);

  if (files.length === 0) {
    return allTrue();
  }

  // New or unrecognised runtime/configuration paths must not silently lose
  // coverage when merge candidates are scoped. Documentation alone is safe.
  const full = files.some((file) => isFullCiFile(file) || !isKnownScopeFile(file));
  // Both Python consumers and the web package validate this shared contract.
  const whatsNewContract = files.some((file) => [
    "frontend/packages/whats-new/version-order.cases.json",
    "frontend/packages/whats-new/releases.schema.json",
  ].includes(file));
  const backend = full || whatsNewContract || files.some(isBackendFile)
    || files.includes("scripts/backend_test_shard.py");
  // The release-notes check runs in the frontend job against the real file.
  // Shared workspace files (root manifests, the lockfile, patches, packages)
  // belong to both apps; each app's own directory only to that app.
  const frontend =
    full
    || files.some((file) => isShippedFrontendFile(file) && !isWebNextFile(file))
    || files.includes("scripts/check_whats_new.py");
  const webNext =
    full || files.some((file) => isShippedFrontendFile(file) && !isSvelteAppFile(file));
  const frontendE2e = full || backend || frontend || files.some(isE2eFile);
  const webNextE2e = full || backend || webNext || files.some(isE2eFile);
  const schema = full || backend || files.some(isSchemaFile);
  // The news vocabulary contract test also depends on the backend permission enum.
  const scripts = full || whatsNewContract || files.some(isScriptTestFile)
    || files.includes("backend/src/eneo/roles/permissions.py");
  const routeMetadata = full || backend || files.includes("scripts/check_route_metadata.py");
  const dockerBackend = full || backend;
  const dockerFrontend = full || frontend;
  const dockerWebNext = full || webNext;
  const dockerDevcontainer = full || files.some((file) => file.startsWith(".devcontainer/"));

  return {
    full,
    backend,
    frontend,
    frontend_e2e: frontendE2e,
    schema,
    scripts,
    route_metadata: routeMetadata,
    docker_backend: dockerBackend,
    docker_frontend: dockerFrontend,
    docker_devcontainer: dockerDevcontainer,
    web_next: webNext,
    web_next_e2e: webNextE2e,
    docker_web_next: dockerWebNext,
  };
}

function isKnownScopeFile(file) {
  return isBackendFile(file) || file.startsWith("frontend/")
    || isScriptTestFile(file) || isE2eFile(file)
    || file.startsWith(".devcontainer/") || /\.mdx?$/i.test(file);
}

function isFullCiFile(file) {
  return file.startsWith(".github/workflows/")
    || file.startsWith(".github/actions/")
    || file.startsWith(".github/scripts/ci-")
    || file === ".pre-commit-config.yaml"
    || file === "Taskfile.yml"
    || file === ".gitignore"
    || file === "docker-compose.e2e.yml"
    || file === "docker-compose.e2e.ci.yml";
}

function isBackendFile(file) {
  // Flow document tests render through the tool runtime's document engine.
  return (
    file.startsWith("backend/") ||
    file.startsWith("tool-runtime/src/tools/documents/") ||
    file.startsWith("tool-runtime/tests/support/") ||
    ["tool-runtime/src/server.ts", "tool-runtime/src/main.ts", "tool-runtime/bun.lock"].includes(
      file,
    )
  );
}

function isShippedFrontendFile(file) {
  return file.startsWith("frontend/") && !file.startsWith("frontend/apps/docs-site/");
}

function isWebNextFile(file) {
  return file.startsWith("frontend/apps/web-next/");
}

function isSvelteAppFile(file) {
  return file.startsWith("frontend/apps/web/");
}

function isE2eFile(file) {
  return file.startsWith("e2e/") || file === "docker-compose.e2e.ci.yml";
}

function isSchemaFile(file) {
  return file.startsWith("frontend/packages/eneo-js/");
}

function isScriptTestFile(file) {
  return file.startsWith("scripts/") || file.startsWith(".github/scripts/");
}

function normalizeFiles(rawFiles) {
  return rawFiles
    .map((file) => file.trim().replaceAll("\\", "/"))
    .map((file) => file.replace(/^\.\//, ""))
    .filter(Boolean);
}

function allTrue() {
  return Object.fromEntries(outputNames.map((name) => [name, true]));
}

function writeOutputs(scope) {
  for (const name of outputNames) {
    console.log(`${name}=${scope[name] ? "true" : "false"}`);
  }
  console.log(`docker=${scope.docker}`);
  console.log(`docker_matrix=${JSON.stringify(scope.docker_matrix)}`);
  console.log(`expected_jobs=${JSON.stringify(scope.expected_jobs)}`);
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
