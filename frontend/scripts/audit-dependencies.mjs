import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  blocksOnSeverity,
  normalizeSeverity,
} from "../../.github/scripts/dependency-audit-severity.mjs";

const cwd = fileURLToPath(new URL("..", import.meta.url));
// Accepted advisories, each pinned to its exact advisory and version range
// and with an expiry: a reviewed reason, not a blanket waiver. A reason that
// rests on how Eneo is configured names a `check`, a test run on every audit;
// while it fails, the advisory is not accepted.
const ACCEPTED = [
  {
    name: "braces",
    url: "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
    vulnerable_versions: "<=3.0.3",
    expires: "2026-12-15",
    reason:
      "mitigated by the tested downstream patch; GitHub withdrew the advisory on 2026-10-23 and no fixed release exists, so the patch and its regression tests stay",
  },
  {
    name: "@sveltejs/kit",
    url: "https://github.com/advisories/GHSA-pfhg-q3qv-9q6r",
    vulnerable_versions: "<3.0.0",
    expires: "2026-12-15",
    reason:
      "open redirect needs use:enhance on a route that accepts paths starting with //; web has no catch-all routes and its enhanced forms are on fixed paths. Fixed only in SvelteKit 3",
  },
  {
    name: "@sveltejs/kit",
    url: "https://github.com/advisories/GHSA-27mw-82g8-phjj",
    vulnerable_versions: "<3.0.0",
    expires: "2026-12-15",
    reason:
      "affects prerendered pages only; web prerenders none. Fixed only in SvelteKit 3",
  },
  {
    name: "@sveltejs/kit",
    url: "https://github.com/advisories/GHSA-3r8g-jcqq-3p5j",
    vulnerable_versions: ">=2.42.0 <=3.1.0",
    expires: "2026-12-15",
    reason:
      "only remote functions parse the affected form data, and neither web nor ui turns on kit.experimental.remoteFunctions. Fixed only in SvelteKit 3.1.1",
    check: "scripts/remote-functions-off.test.mjs",
  },
  {
    name: "deepmerge",
    url: "https://github.com/advisories/GHSA-gcqx-w48m-w2h4",
    vulnerable_versions: ">=4.2.0 <=4.3.1",
    expires: "2026-11-27",
    reason:
      "build-time only: @sveltejs/vite-plugin-svelte and adapter-node's @rollup/plugin-node-resolve merge the build's own config, never request input, and nothing ships it to the runtime. No fixed release exists (4.3.1 is the latest)",
  },
];
export function evaluate(report, now = new Date(), failedChecks = []) {
  assert.ok(
    report && typeof report === "object" && !Array.isArray(report),
    "Invalid Bun audit report.",
  );
  const errors = [];
  const warnings = [];
  const accepted = [];
  const holds = (entry) =>
    now < new Date(`${entry.expires}T00:00:00Z`) &&
    !failedChecks.includes(entry.check);
  for (const entry of ACCEPTED) {
    if (now >= new Date(`${entry.expires}T00:00:00Z`)) {
      errors.push(
        `Review ${entry.name} ${entry.url} and remove/renew its documented exception before ${entry.expires}.`,
      );
    }
    if (failedChecks.includes(entry.check)) {
      errors.push(
        `${entry.name} ${entry.url} is no longer accepted: ${entry.check} failed.`,
      );
    }
  }
  for (const [name, advisories] of Object.entries(report)) {
    assert.ok(Array.isArray(advisories), `Invalid advisory list for ${name}.`);
    for (const advisory of advisories) {
      const entry = ACCEPTED.find(
        (entry) =>
          entry.name === name &&
          entry.url === advisory.url &&
          entry.vulnerable_versions === advisory.vulnerable_versions,
      );
      if (entry && holds(entry)) {
        accepted.push(
          `${name}: ${advisory.url} accepted, ${entry.reason}; review expires ${entry.expires}.`,
        );
        continue;
      }
      const severity = normalizeSeverity(advisory.severity);
      const message = `${name}: ${severity ?? "unknown"} ${advisory.url}`;
      if (!severity || blocksOnSeverity(severity)) errors.push(message);
      else warnings.push(message);
    }
  }
  return { errors, warnings, accepted };
}

export function run(argv) {
  const regression = spawnSync(
    process.execPath,
    ["--test", "--test-concurrency=1", "scripts/security-patches.test.mjs"],
    { cwd, stdio: "inherit" },
  );
  assert.equal(
    regression.status,
    0,
    "The installed dependency security patch must pass its behavior tests.",
  );
  const failedChecks = [];
  for (const { check } of ACCEPTED) {
    if (!check) continue;
    const result = spawnSync(
      process.execPath,
      ["--test", "--test-concurrency=1", check],
      { cwd, stdio: "inherit" },
    );
    if (result.status !== 0) failedChecks.push(check);
  }
  const audit = spawnSync("bun", ["audit", "--json"], {
    cwd,
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
  });
  assert.ok(
    audit.status === 0 || audit.status === 1,
    "bun audit did not complete successfully",
  );
  const report = JSON.parse(audit.stdout);
  if (argv[0]) writeFileSync(argv[0], JSON.stringify(report, null, 2) + "\n");
  const result = evaluate(report, new Date(), failedChecks);
  const escape = (message) =>
    message
      .replaceAll("%", "%25")
      .replaceAll("\r", "%0D")
      .replaceAll("\n", "%0A");
  for (const message of result.accepted) console.log(message);
  for (const message of result.warnings)
    console.log(`::warning::${escape(message)}`);
  for (const message of result.errors)
    console.error(`::error::${escape(message)}`);
  return result.errors.length > 0 ? 1 : 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exitCode = run(process.argv.slice(2));
}
