import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const cwd = fileURLToPath(new URL("..", import.meta.url));
// Accepted advisories, each pinned to its exact advisory and version range
// and with an expiry: a reviewed reason, not a blanket waiver.
const ACCEPTED = [
  {
    name: "braces",
    url: "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
    vulnerable_versions: "<=3.0.3",
    expires: "2026-11-05",
    reason: "mitigated by the tested downstream patch",
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
    name: "deepmerge",
    url: "https://github.com/advisories/GHSA-gcqx-w48m-w2h4",
    vulnerable_versions: ">=4.2.0 <=4.3.1",
    expires: "2026-11-27",
    reason:
      "build-time only: @sveltejs/vite-plugin-svelte and adapter-node's @rollup/plugin-node-resolve merge the build's own config, never request input, and nothing ships it to the runtime. No fixed release exists (4.3.1 is the latest)",
  },
];
for (const entry of ACCEPTED) {
  assert.ok(
    new Date() < new Date(`${entry.expires}T00:00:00Z`),
    `Review ${entry.name} ${entry.url} and remove/renew its documented exception before ${entry.expires}.`,
  );
}
const regression = spawnSync(
  process.execPath,
  ["--test", "scripts/security-patches.test.mjs"],
  { cwd, stdio: "inherit" },
);
assert.equal(
  regression.status,
  0,
  "The installed dependency security patch must pass its behavior tests.",
);
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
if (process.argv[2])
  writeFileSync(process.argv[2], JSON.stringify(report, null, 2) + "\n");
let blocking = 0;
for (const [name, advisories] of Object.entries(report)) {
  for (const advisory of advisories) {
    const accepted = ACCEPTED.find(
      (entry) =>
        entry.name === name &&
        entry.url === advisory.url &&
        entry.vulnerable_versions === advisory.vulnerable_versions,
    );
    if (accepted) {
      console.log(
        `${name}: ${advisory.url} accepted, ${accepted.reason}; review expires ${accepted.expires}.`,
      );
      continue;
    }
    if (
      name === "katex" &&
      advisory.url === "https://github.com/advisories/GHSA-238p-pmpm-9mq7"
    ) {
      // Low (CVSS 2.1): only exploitable once the page already has prototype
      // pollution. Every dependent (rehype-katex, @streamdown/math, mermaid,
      // nextra, micromark-extension-math) still pins ^0.16; move to 0.18.2
      // when they do.
      assert.ok(
        new Date() < new Date("2026-12-01T00:00:00Z"),
        "Bump katex to 0.18.2 (dependents permitting) or renew the GHSA-238p-pmpm-9mq7 exception before 2026-12-01.",
      );
      console.log(
        "katex: GHSA-238p-pmpm-9mq7 accepted (low, needs pre-existing prototype pollution); review expires 2026-12-01.",
      );
      continue;
    }
    console.error(`${name}: ${advisory.severity} ${advisory.url}`);
    blocking++;
  }
}
process.exitCode = blocking > 0 ? 1 : 0;
