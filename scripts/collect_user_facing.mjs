#!/usr/bin/env node

// Collect the raw material for a What's new entry: the "## User-facing"
// sections of the pull requests merged since the previous final release.
// Deterministic and model-free; an assistant or a human writes the entry from
// its output. See frontend/packages/whats-new/PLAYBOOK.md.
//
// Usage:
//   node scripts/collect_user_facing.mjs [--since vX.Y.Z] [--head origin/develop]
//                                        [--format markdown|json] [--no-fetch]
//
// The window is the git range <since>..<head>: every commit on the head ref
// that the previous release does not contain. Final tags live on release
// branches and are not ancestors of develop, so `git describe` cannot find
// them; the range still yields exactly the commits added since that release
// line was cut. Pull requests are read from squash-merge subjects ("… (#123)").

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

import {
  isNegative,
  userFacingSection,
} from "../.github/scripts/check-user-facing.mjs";

const PR_NUMBER_RE = /\(#(\d+)\)\s*$/;

/** Pull request numbers from squash-merge subjects; subjects without one are kept. */
export function pullRequestNumbers(subjects) {
  const numbers = [];
  const unlinked = [];
  for (const subject of subjects) {
    const match = PR_NUMBER_RE.exec(subject);
    if (match) numbers.push(Number(match[1]));
    else if (subject.trim()) unlinked.push(subject.trim());
  }
  return { numbers: [...new Set(numbers)], unlinked };
}

/** Split pull requests by what their "## User-facing" section says. */
export function classify(pullRequests) {
  const described = [];
  const negative = [];
  const missing = [];
  for (const pr of pullRequests) {
    const section = userFacingSection(pr.body ?? "");
    if (section === null || section === "") missing.push(pr);
    else if (isNegative(section)) negative.push(pr);
    else described.push({ ...pr, section });
  }
  return { described, negative, missing };
}

export function renderMarkdown({ since, head, unlinked }, groups) {
  const lines = [
    `# User-facing changes since ${since}`,
    "",
    `Range \`${since}..${head}\`: ${groups.described.length} pull request(s) describe a change, ` +
      `${groups.negative.length} say No, ${groups.missing.length} have no section.`,
    "",
    "## Described",
  ];
  if (groups.described.length === 0) lines.push("", "(none)");
  for (const pr of groups.described) {
    lines.push("", `### #${pr.number} ${pr.title}`, "", pr.section);
  }
  if (groups.missing.length > 0) {
    lines.push(
      "",
      "## No User-facing section",
      "",
      "Read the title and the Changes section; say in the entry's PR which of these you used.",
      "",
    );
    for (const pr of groups.missing) lines.push(`- #${pr.number} ${pr.title}`);
  }
  if (unlinked.length > 0) {
    lines.push("", "## Commits without a pull request", "");
    for (const subject of unlinked) lines.push(`- ${subject}`);
  }
  return `${lines.join("\n")}\n`;
}

export function renderJson({ since, head, unlinked }, groups) {
  const brief = ({ number, title, url }) => ({ number, title, url });
  return `${JSON.stringify(
    {
      since,
      head,
      described: groups.described.map((pr) => ({ ...brief(pr), section: pr.section })),
      negative: groups.negative.map(brief),
      missing: groups.missing.map(brief),
      unlinked,
    },
    null,
    2,
  )}\n`;
}

function run(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`,
    );
  }
  return result.stdout;
}

function newestFinalRelease() {
  const releases = JSON.parse(
    run("gh", [
      "release", "list", "--exclude-pre-releases", "--exclude-drafts",
      "--limit", "1", "--json", "tagName",
    ]),
  );
  if (releases.length === 0) throw new Error("no final release found; pass --since vX.Y.Z");
  return releases[0].tagName;
}

function mergedSubjects(since, head) {
  return run("git", ["log", "--format=%s", `${since}..${head}`])
    .split("\n")
    .filter(Boolean);
}

function fetchPullRequests(numbers) {
  const wanted = new Set(numbers);
  const found = new Map();
  const fields = "number,title,body,url,mergedAt";
  const listed = JSON.parse(
    run("gh", ["pr", "list", "--state", "merged", "--limit", "500", "--json", fields]),
  );
  for (const pr of listed) if (wanted.has(pr.number)) found.set(pr.number, pr);
  for (const number of numbers) {
    if (found.has(number)) continue;
    found.set(number, JSON.parse(run("gh", ["pr", "view", String(number), "--json", fields])));
  }
  return numbers.map((number) => found.get(number)).sort((a, b) => a.mergedAt.localeCompare(b.mergedAt));
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith("--")) throw new Error(`unexpected argument ${arg}`);
    const key = arg.slice(2);
    if (key === "self-test" || key === "no-fetch") args[key] = true;
    else args[key] = argv[++i];
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args["self-test"]) {
    runSelfTest();
    return 0;
  }
  const format = args.format ?? "markdown";
  if (!["markdown", "json"].includes(format)) throw new Error(`unknown --format ${format}`);
  if (!args["no-fetch"]) run("git", ["fetch", "--quiet", "--tags", "origin"]);
  const since = args.since ?? newestFinalRelease();
  const head = args.head ?? "origin/develop";
  const { numbers, unlinked } = pullRequestNumbers(mergedSubjects(since, head));
  const groups = classify(fetchPullRequests(numbers));
  const render = format === "json" ? renderJson : renderMarkdown;
  process.stdout.write(render({ since, head, unlinked }, groups));
  return 0;
}

function runSelfTest() {
  const parsed = pullRequestNumbers([
    "feat(skills): add on-demand mode (#616)",
    "fix(crawler): restore HTTPS certificate handling (#799)",
    "feat(skills): add on-demand mode (#616)",
    "chore: bump version",
    "",
  ]);
  assert.deepEqual(parsed, { numbers: [616, 799], unlinked: ["chore: bump version"] });

  const body = (section) => `## Changes\nx\n\n## User-facing\n${section}\n\n## Testing\ny\n`;
  const prs = [
    { number: 1, title: "feat: a", url: "u1", body: body("You can now do A.\nAlso B.") },
    { number: 2, title: "chore: b", url: "u2", body: body("No") },
    { number: 3, title: "fix: c", url: "u3", body: "## Changes\nold template\n" },
    { number: 4, title: "fix: d", url: "u4", body: body("<!-- hint only -->") },
  ];
  const groups = classify(prs);
  assert.deepEqual(groups.described.map((pr) => pr.number), [1]);
  assert.equal(groups.described[0].section, "You can now do A.\nAlso B.");
  assert.deepEqual(groups.negative.map((pr) => pr.number), [2]);
  assert.deepEqual(groups.missing.map((pr) => pr.number), [3, 4]);

  const context = { since: "v2.1.1", head: "origin/develop", unlinked: ["chore: bump version"] };
  const markdown = renderMarkdown(context, groups);
  assert.match(markdown, /^# User-facing changes since v2\.1\.1\n/);
  assert.match(markdown, /1 pull request\(s\) describe a change, 1 say No, 2 have no section/);
  assert.match(markdown, /### #1 feat: a\n\nYou can now do A\.\nAlso B\.\n/);
  assert.match(markdown, /## No User-facing section[\s\S]*- #3 fix: c\n- #4 fix: d\n/);
  assert.match(markdown, /## Commits without a pull request\n\n- chore: bump version\n$/);
  assert.doesNotMatch(markdown, /#2 chore: b/);

  const json = JSON.parse(renderJson(context, groups));
  assert.deepEqual(json.described, [
    { number: 1, title: "feat: a", url: "u1", section: "You can now do A.\nAlso B." },
  ]);
  assert.deepEqual(json.negative, [{ number: 2, title: "chore: b", url: "u2" }]);
  assert.deepEqual(json.missing.map((pr) => pr.number), [3, 4]);
  assert.deepEqual(json.unlinked, ["chore: bump version"]);

  const empty = renderMarkdown({ since: "v1", head: "h", unlinked: [] }, classify([]));
  assert.match(empty, /## Described\n\n\(none\)\n$/);

  console.log("collect-user-facing self-test passed");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
