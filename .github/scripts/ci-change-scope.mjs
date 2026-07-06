#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

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
];

if (process.argv.includes("--self-test")) {
  runSelfTest();
  process.exit(0);
}

try {
  const filesPath = getArgValue("--files");
  const files = filesPath
    ? fs.readFileSync(filesPath, "utf8").split("\n")
    : process.argv.slice(2).filter((arg) => !arg.startsWith("--"));

  writeOutputs(classify(files));
} catch (error) {
  console.error(`::warning::Failed to classify changed files. Running full CI. ${error.message}`);
  writeOutputs(allTrue());
}

function classify(rawFiles) {
  const files = normalizeFiles(rawFiles);

  if (files.length === 0) {
    return allTrue();
  }

  const full = files.some(isFullCiFile);
  const backend = full || files.some(isBackendFile);
  const frontend = full || files.some(isShippedFrontendFile);
  const frontendE2e = full || backend || frontend || files.some(isE2eFile);
  const schema = full || backend || files.some(isSchemaFile);
  const scripts = full || files.some(isScriptTestFile);
  const routeMetadata = full || backend || files.includes("scripts/check_route_metadata.py");
  const dockerBackend = full || backend;
  const dockerFrontend = full || frontend;
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
  };
}

function isFullCiFile(file) {
  return file.startsWith(".github/workflows/")
    || file === ".github/scripts/ci-change-scope.mjs"
    || file === ".pre-commit-config.yaml"
    || file === "Taskfile.yml"
    || file === ".gitignore"
    || file === "docker-compose.e2e.yml"
    || file === "docker-compose.e2e.ci.yml";
}

function isBackendFile(file) {
  return file.startsWith("backend/");
}

function isShippedFrontendFile(file) {
  return file.startsWith("frontend/") && !file.startsWith("frontend/apps/docs-site/");
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
  assert.deepEqual(
    classify(["frontend/apps/docs-site/src/content/contributing/project-roadmap.mdx"]),
    {
      full: false,
      backend: false,
      frontend: false,
      frontend_e2e: false,
      schema: false,
      scripts: false,
      route_metadata: false,
      docker_backend: false,
      docker_frontend: false,
      docker_devcontainer: false,
    },
    "docs-site-only changes should not run expensive app/backend CI",
  );

  assert.equal(classify(["backend/src/eneo/server/main.py"]).backend, true);
  assert.equal(classify(["backend/src/eneo/server/main.py"]).frontend_e2e, true);
  assert.equal(classify(["backend/src/eneo/server/main.py"]).schema, true);
  assert.equal(classify(["backend/src/eneo/server/main.py"]).route_metadata, true);
  assert.equal(classify(["backend/src/eneo/server/main.py"]).docker_backend, true);

  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).frontend, true);
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).frontend_e2e, true);
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).docker_frontend, true);
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).schema, false);

  assert.equal(classify(["frontend/knip.json"]).frontend, true);
  assert.equal(classify(["frontend/knip.json"]).frontend_e2e, true);
  assert.equal(classify(["frontend/packages/eneo-js/src/types/schema.d.ts"]).schema, true);
  assert.equal(classify([".github/scripts/project-intake.mjs"]).scripts, true);
  assert.equal(classify(["e2e/mock_model_server.py"]).frontend_e2e, true);
  assert.equal(classify([".devcontainer/Dockerfile"]).docker_devcontainer, true);

  const fullScope = classify([".github/workflows/ci.yml"]);
  for (const name of outputNames) {
    assert.equal(fullScope[name], true, `CI workflow changes should enable ${name}`);
  }

  const docsWorkflowScope = classify([".github/workflows/deploy_docs.yml"]);
  for (const name of outputNames) {
    assert.equal(docsWorkflowScope[name], true, `workflow changes should enable ${name}`);
  }

  const emptyScope = classify([]);
  for (const name of outputNames) {
    assert.equal(emptyScope[name], true, `empty change lists should fail open for ${name}`);
  }

  console.log("ci-change-scope self-test passed");
}
