// Lists, with Playwright itself, the cases each web-next E2E leg of ci.yml selects, and
// fails unless every case runs in exactly one leg (or the upload phase) and no case of a
// walk the walk legs take runs in the screens or rest leg. A walk viewport of a device no
// walk leg takes would otherwise slip into the rest leg unnoticed.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const app = path.join(root, "frontend/apps/web-next");
const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
const job = workflow.split("\n  frontend-web-next-e2e:\n")[1].split("\n  schema-drift:\n")[0];
const legs = [
  ...job.matchAll(/^ {10}- \{ leg: ([a-z0-9-]+), grep: "([^"]+)", grep_invert: "([^"]+)"/gm),
].map(([, leg, grep, invert]) => ({ leg, grep, invert }));
if (legs.length < 2) throw new Error("no web-next E2E legs found in ci.yml");

/** The cases a selection holds, keyed by their title path, with their tags. */
function list(...args) {
  const playwright = path.join(app, "node_modules/.bin/playwright");
  const options = ["test", "--list", "--pass-with-no-tests", "--reporter=json", ...args];
  const run = spawnSync(playwright, options, {
    cwd: app,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    // The specs skip themselves without a target; listing needs none.
    env: { ...process.env, E2E_BASE_URL: process.env.E2E_BASE_URL ?? "http://localhost:8124" },
  });
  if (run.status !== 0) {
    // A spec that throws while loading (a viewport without a device group) is in the report.
    let errors = "";
    try {
      errors = JSON.parse(run.stdout).errors.map((error) => error.message).join("\n");
    } catch {}
    const cause = [run.error?.message, errors, run.stderr].filter(Boolean).join("\n");
    throw new Error(`playwright --list ${args.join(" ")} failed:\n${cause}`);
  }
  const cases = new Map();
  const visit = (suite, titles) => {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests) {
        if (test.projectName === "setup") continue;
        cases.set([...titles, spec.title].join(" › "), spec.tags);
      }
    }
    for (const child of suite.suites ?? []) visit(child, [...titles, child.title]);
  };
  for (const suite of JSON.parse(run.stdout).suites) visit(suite, [suite.title]);
  return cases;
}

const all = list();
const selections = [
  ...legs.map(({ leg, grep, invert }) => ({ leg, cases: list("--grep", grep, "--grep-invert", invert) })),
  { leg: "upload phase", cases: list("--grep", "@upload-worker") },
];
const walkTags = new Set(
  legs.filter(({ grep }) => grep.startsWith("@"))
    .flatMap(({ grep }) => grep.split("|").map((cell) => cell.split(" ")[0].slice(1))),
);

const problems = [];
for (const [key, tags] of all) {
  const owners = selections.filter(({ cases }) => cases.has(key)).map(({ leg }) => leg);
  if (owners.length !== 1) problems.push(`${key}: runs in ${owners.length ? owners.join(", ") : "no leg"}`);
  const walk = tags.find((tag) => walkTags.has(tag));
  const { grep } = legs.find(({ leg }) => leg === owners[0]) ?? {};
  if (walk && grep && !grep.startsWith("@")) problems.push(`${key}: a @${walk} case runs in ${owners[0]}`);
}
for (const { leg, cases } of selections) console.log(`${leg}: ${cases.size} cases`);
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`All ${all.size} cases run in exactly one leg.`);
