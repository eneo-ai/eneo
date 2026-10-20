import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const config = fileURLToPath(new URL("../../.gitleaks.toml", import.meta.url));
// Assemble public examples so this test does not itself introduce key findings.
const examples = [
  ["docker-compose.e2e.yml", ["yPIAaWTENh5knUuz75NYHbl", "R3672X-7lH-W6AD4F1hs="]],
  ["docker-compose.e2e.ci.yml", ["yPIAaWTENh5knUuz75NYHbl", "R3672X-7lH-W6AD4F1hs="]],
  ["backend/tests/unittests/model_providers/test_provider_connection_probe.py", ["sk-live-", "secret-1234"]],
  ["backend/tests/unittests/model_providers/test_provider_connection_check.py", ["sk-live-", "secret-1234"]],
  ["backend/tests/integration/model_providers/test_provider_connection_check.py", ["sk-live-", "secret-1234"]],
  ["backend/tests/unittests/model_providers/test_model_provider_masked_api_key.py", ["sk-live-", "0123456789abcd"]],
  ["frontend/apps/web-next/src/lib/api/schema.d.ts", ["sk-proj-", "abc123xyz"]],
  ["frontend/apps/web-next/src/lib/api/schema.d.ts", ["sk-proj-", "abc123..."]],
  ["frontend/apps/web-next/src/lib/api/schema.d.ts", ["inp_", "3f5f2f7f7f...d9a1"]],
  ["frontend/apps/web-next/src/lib/api/schema.d.ts", ["ina_", "6f2c9b3a8f...7b31"]],
  ["backend/tests/integration/test_model_provider_outbound_headers.py", ["sk-test-", "12345678"]],
  // The content-service tests lived here before they were split; earlier commits are still scanned.
  ["backend/tests/unittests/integration/test_sharepoint_content_service.py", ["integration_knowledge_id=", "ik.id"]],
  ["backend/tests/unittests/integration/infrastructure/content_service/test_sharepoint_content_service.py", ["integration_knowledge_id=", "ik.id"]],
  ["backend/tests/unittests/integration/infrastructure/content_service/test_sharepoint_content_service.py", ["integration_knowledge_id=", "knowledge_id"]],
  ["backend/tests/unittests/integration/infrastructure/content_service/test_sharepoint_index.py", ["integration_knowledge_id=", "knowledge_id"]],
  ["backend/tests/unittests/integration/infrastructure/content_service/test_sharepoint_reconciliation.py", ["integration_knowledge_id=", "ik.id"]],
  ["backend/tests/unittests/integration/test_sharepoint_sync_ledger.py", ["integration_knowledge_id=", "ik.id"]],
  ["backend/tests/unittests/integration/test_sharepoint_failed_items.py", ["integration_knowledge_id=", "ik.id"]],
  ["backend/tests/unittests/observability/test_error_text.py", ["v1.eyJhdWQiOiJ4In0.", "c2lnbmF0dXJl"]],
].map(([path, parts]) => ({ path, value: parts.join("") }));

function repository(t) {
  const root = mkdtempSync(join(tmpdir(), "eneo-gitleaks-policy-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  copyFileSync(config, join(root, ".gitleaks.toml"));
  return root;
}

function writeExamples(root, transform = (example) => example, padding = "") {
  const files = new Map();
  for (const original of examples) {
    const { path, value } = transform(original);
    files.set(path, (files.get(path) ?? padding) + `api_key = "${value}"\n`);
  }
  for (const [path, content] of files) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), content);
  }
}

function scan(root, mode = "dir", options = [], expectedCount = 0) {
  const report = join(root, "findings.json");
  rmSync(report, { force: true });
  const result = spawnSync(process.env.GITLEAKS_BIN ?? "gitleaks", [
    mode, "--redact=100", "--no-banner", "--report-format=json",
    `--report-path=${report}`, ...options, ".",
  ], { cwd: root, encoding: "utf8", timeout: 15000, env: { ...process.env, GOMAXPROCS: "1" } });
  assert.ifError(result.error);
  assert.equal(result.status, expectedCount ? 1 : 0, result.stderr);
  const findings = JSON.parse(readFileSync(report, "utf8"));
  assert.equal(findings.length, expectedCount, result.stderr);
  return findings;
}

function git(root, ...args) {
  const result = spawnSync("git", [
    "-c", "user.name=Gitleaks policy test", "-c", "user.email=gitleaks@example.invalid",
    "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", ...args,
  ], { cwd: root, encoding: "utf8", timeout: 15000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

test("only the reviewed examples are excluded from the built-in generic rule", (t) => {
  const root = repository(t);
  writeExamples(root);
  writeFileSync(join(root, "defaults.toml"), "[extend]\nuseDefault = true\n");
  const findings = scan(root, "dir", ["--config=defaults.toml"], examples.length);
  assert.ok(findings.every((finding) => finding.RuleID === "generic-api-key"));
  scan(root);
});

test("changed values in every reviewed file are still detected", (t) => {
  const root = repository(t);
  writeExamples(root, ({ path, value }) => ({ path, value: `${value}Z9` }));
  scan(root, "dir", [], examples.length);
});

test("reviewed values are still detected outside the exact allowed paths", (t) => {
  const root = repository(t);
  for (const transform of [
    ({ path, value }) => ({ path: `other/${path}`, value }),
    ({ path, value }) => ({ path: `${path}.backup`, value }),
  ]) writeExamples(root, transform);
  scan(root, "dir", [], examples.length * 2);
});

test("an allowed value on the same line cannot hide a different key or another rule", (t) => {
  const root = repository(t);
  const { path, value } = examples[2];
  mkdirSync(dirname(join(root, path)), { recursive: true });
  const novel = ["sk-live-", "q8Z2mR7vL4nB6xT9"].join("");
  const githubToken = "ghp_" + "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0iL3oR6";
  writeFileSync(join(root, path), `api_key = "${value}"; other_key = "${novel}"\ntoken = "${githubToken}"\n`);
  const rules = scan(root, "dir", [], 2).map((finding) => finding.RuleID).sort();
  assert.deepEqual(rules, ["generic-api-key", "github-pat"]);
});

test("Git scans accept reviewed examples after line moves and a squash commit", (t) => {
  const root = repository(t);
  git(root, "init", "--quiet");
  git(root, "add", ".gitleaks.toml");
  git(root, "commit", "--quiet", "-m", "Base");
  const base = git(root, "rev-parse", "HEAD");
  writeExamples(root);
  git(root, "add", ".");
  git(root, "commit", "--quiet", "-m", "Examples");
  writeExamples(root, (example) => example, "\n".repeat(20));
  git(root, "add", ".");
  git(root, "commit", "--quiet", "-m", "Move lines");
  const head = git(root, "rev-parse", "HEAD");
  scan(root, "git", [`--log-opts=${base}..HEAD`]);
  git(root, "reset", "--soft", base);
  git(root, "commit", "--quiet", "-m", "Squashed examples");
  assert.notEqual(git(root, "rev-parse", "HEAD"), head);
  scan(root, "git", [`--log-opts=${base}..HEAD`]);
});
