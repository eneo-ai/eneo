import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const cwd = fileURLToPath(new URL("..", import.meta.url));
// A mitigation with an expiry, not a blanket waiver for braces.
assert.ok(
  new Date() < new Date("2026-11-05T00:00:00Z"),
  "Review the braces security patch and remove/renew its documented exception before 2026-11-05.",
);
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
    if (
      name === "braces" &&
      advisory.url === "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm" &&
      advisory.vulnerable_versions === "<=3.0.3"
    ) {
      console.log(
        "braces: GHSA-vfj7-8cjw-p6xm mitigated by the tested downstream patch; review expires 2026-11-05.",
      );
      continue;
    }
    console.error(`${name}: ${advisory.severity} ${advisory.url}`);
    blocking++;
  }
}
process.exitCode = blocking > 0 ? 1 : 0;
