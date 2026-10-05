#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const outputNames = [
  "full",
  "backend",
  "frontend",
  "frontend_e2e",
  "schema",
  "backend_scripts",
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
  // Both Python consumers and the web package validate this shared contract.
  const whatsNewContract = files.some((file) => [
    "frontend/packages/whats-new/version-order.cases.json",
    "frontend/packages/whats-new/releases.schema.json",
  ].includes(file));
  const backend = full || whatsNewContract || files.some(isBackendFile)
    || files.includes("scripts/backend_test_shard.py");
  // The release-notes check runs in the frontend job against the real file.
  const frontend =
    full || files.some(isShippedFrontendFile) || files.includes("scripts/check_whats_new.py");
  const frontendE2e = full || backend || frontend || files.some(isE2eFile);
  const schema = full || backend || files.some(isSchemaFile);
  // Some script tests import product modules, so any backend change runs them (locally they run on a narrower trigger).
  const backendScripts = backend;
  const scripts = full || whatsNewContract || files.some(isScriptTestFile);
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
    backend_scripts: backendScripts,
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
  assertOutboundRenameScope();
  assert.deepEqual(
    classify(["frontend/apps/docs-site/src/content/contributing/project-roadmap.mdx"]),
    {
      full: false,
      backend: false,
      frontend: false,
      frontend_e2e: false,
      schema: false,
      backend_scripts: false,
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

  for (const file of [
    "backend/src/eneo/server/main.py",
    "backend/scripts/ai_builder_release_gate.py",
    "backend/tests/scripts/test_ai_builder_release_gate.py",
    "backend/tests/conftest.py",
    "backend/pytest.ini",
  ]) {
    assert.equal(classify([file]).backend_scripts, true, `${file} should run the backend script tests`);
  }
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).backend_scripts, false);

  assert.equal(classify(["scripts/backend_test_shard.py"]).backend, true);
  assert.equal(classify(["scripts/backend_test_shard.py"]).scripts, true);

  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).frontend, true);
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).frontend_e2e, true);
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).docker_frontend, true);
  assert.equal(classify(["frontend/apps/web/src/routes/+page.svelte"]).schema, false);

  assert.equal(classify(["frontend/knip.json"]).frontend, true);
  assert.equal(classify(["frontend/knip.json"]).frontend_e2e, true);
  assert.equal(classify(["frontend/packages/eneo-js/src/types/schema.d.ts"]).schema, true);
  assert.equal(classify([".github/scripts/project-intake.mjs"]).scripts, true);
  assert.equal(classify(["scripts/check_whats_new.py"]).frontend, true);
  assert.equal(classify(["scripts/check_whats_new.py"]).scripts, true);
  for (const name of ["version-order.cases.json", "releases.schema.json"]) {
    const contractScope = classify([`frontend/packages/whats-new/${name}`]);
    assert.equal(contractScope.backend, true);
    assert.equal(contractScope.frontend, true);
    assert.equal(contractScope.scripts, true);
  }
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

function assertOutboundRenameScope() {
  // An outbound rename must still run tests of the removed backend code.
  const lines = fs
    .readFileSync(new URL("../workflows/ci.yml", import.meta.url), "utf8")
    .split("\n");
  const step = lines.findIndex((line) => line.trim() === "id: changed-files");
  const run = lines.findIndex(
    (line, index) => index > step && line.trim() === "run: |",
  );
  assert.ok(step >= 0 && run > step, "changed-file workflow step must exist");
  const script = [];
  for (const line of lines.slice(run + 1)) {
    if (line.trim() && !line.startsWith("          ")) break;
    script.push(line.slice(10));
  }
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "eneo-ci-rename-"));
  const env = {
    PATH: process.env.PATH,
    LANG: "C",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
  };
  const git = (...args) =>
    execFileSync("git", args, { cwd: root, env, timeout: 5000 });
  const source = "backend/rename-fixture.py";
  const destination =
    "frontend/apps/docs-site/src/content/docs/rename-fixture.md";
  try {
    git("init", "-b", "feature/rename-fixture");
    git("config", "user.name", "CCimen");
    git("config", "user.email", "test@example.com");
    git("config", "diff.renames", "true");
    fs.mkdirSync(path.join(root, "backend"));
    fs.writeFileSync(path.join(root, source), "Synthetic rename fixture\n");
    git("add", "--", source);
    git("commit", "-m", "Add synthetic backend fixture");
    const base = git("rev-parse", "HEAD").toString().trim();
    fs.mkdirSync(path.dirname(path.join(root, destination)), {
      recursive: true,
    });
    fs.renameSync(path.join(root, source), path.join(root, destination));
    git("add", "--", source, destination);
    git("commit", "-m", "Move fixture to docs");
    const head = git("rev-parse", "HEAD").toString().trim();
    for (const before of [base, "0".repeat(40)]) {
      execFileSync("bash", ["-c", script.join("\n")], {
        cwd: root,
        timeout: 5000,
        env: {
          ...env,
          EVENT_NAME: "push",
          BEFORE_SHA: before,
          HEAD_SHA: head,
          RUNNER_TEMP: root,
          GITHUB_OUTPUT: path.join(root, "outputs"),
          GITHUB_STEP_SUMMARY: path.join(root, "summary"),
        },
      });
      const files = fs
        .readFileSync(path.join(root, "changed-files.txt"), "utf8")
        .split("\n");
      assert.equal(
        classify(files).backend_scripts,
        true,
        "outbound backend rename must run its tooling tests",
      );
    }
  } finally {
    fs.rmSync(root, { recursive: true });
  }
}
