#!/usr/bin/env node

import fs from "node:fs";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { getSectionWithPresence, issueLabelChanges } from "./label-policy.mjs";

const dryRun = process.argv.includes("--dry-run");
const selfTest = process.argv.includes("--self-test");
const marker = "<!-- eneo-project-intake:missing-epic -->";
const repo = process.env.GITHUB_REPOSITORY || "eneo-ai/eneo";
const eventPath = process.env.GITHUB_EVENT_PATH;
const epicSectionHeadings = ["Parent epic", "Epic", "Parent issue"];

if (selfTest) {
  runSelfTest();
  process.exit(0);
}

if (!eventPath) {
  console.log("GITHUB_EVENT_PATH is not set. Nothing to validate.");
  process.exit(0);
}

const event = JSON.parse(fs.readFileSync(eventPath, "utf8"));
const issue = event.issue;
const pullRequest = event.pull_request;

if (!issue && !pullRequest) {
  console.log("No issue or pull request payload found. Nothing to validate.");
  process.exit(0);
}

if (issue) {
  // Re-read after queued edits or a manual rerun instead of applying stale labels.
  const current = runGh(["api", `repos/${repo}/issues/${issue.number}`], { capture: true });
  await handleIssue(JSON.parse(current.stdout));
} else {
  await handlePullRequest(pullRequest);
}

async function handleIssue(item) {
  const labels = getLabelNames(item);
  const kind = inferIssueKind(item, labels);

  if (kind) {
    addLabel(item.number, `kind:${kind}`);
    if (!labels.includes(`kind:${kind}`)) labels.push(`kind:${kind}`);
  }

  const changes = issueLabelChanges({
    body: item.body || "", previousBody: event.changes?.body?.from, labels,
  });
  if (changes.add.length || changes.remove.length) {
    const args = ["issue", "edit", String(item.number), "--repo", repo];
    if (changes.add.length) args.push("--add-label", changes.add.join(","));
    if (changes.remove.length) args.push("--remove-label", changes.remove.join(","));
    runGh(args);
  }

  if (kind !== "task") {
    return;
  }

  // The native sub-issue relationship is the parent. The form field is only
  // the input used to create it when it is missing.
  const epic = taskEpicLink(item);
  if (epic.linked || (epic.number && linkToEpic(item, epic.number))) {
    if (labels.includes("needs:epic")) removeLabel(item.number, "needs:epic");
    return;
  }

  addLabel(item.number, "needs:epic");
  addMissingEpicComment(item.number);
}

async function handlePullRequest(payload) {
  // Re-read so links made in the Development sidebar and queued edits count.
  const current = runGh([
    "pr", "view", String(payload.number), "--repo", repo,
    "--json", "isDraft,baseRefName,labels,closingIssuesReferences",
  ], { capture: true });
  const defaultBranch = event.repository?.default_branch || "develop";
  const change = taskLinkLabelChange(JSON.parse(current.stdout), defaultBranch);

  if (change === "add") {
    addLabel(payload.number, "needs:task-link");
    console.log(`PR #${payload.number} closes no issue. Added needs:task-link.`);
  } else if (change === "remove") {
    removeLabel(payload.number, "needs:task-link");
  }
}

// Only ready PRs into the default branch close issues on merge. Release
// backports and stacked PRs reach the task through that default-branch PR.
function taskLinkLabelChange(pr, defaultBranch) {
  const hasLabel = getLabelNames(pr).includes("needs:task-link");
  const missing = !pr.isDraft
    && pr.baseRefName === defaultBranch
    && !(pr.closingIssuesReferences || []).length;

  if (missing && !hasLabel) return "add";
  if (!missing && hasLabel) return "remove";
  return null;
}

function inferIssueKind(item, labels) {
  for (const label of labels) {
    const match = /^kind:(epic|task|finding|chore)$/i.exec(label);
    if (match) {
      return match[1].toLowerCase();
    }
  }

  const title = item.title || "";
  const body = item.body || "";

  if (/^\[epic\]/i.test(title) || hasHeading(body, "Roadmap version")) {
    return "epic";
  }

  if (/^\[task\]/i.test(title) || hasHeading(body, "Parent epic")) {
    return "task";
  }

  if (/^\[finding\]/i.test(title) || hasHeading(body, "Finding")) {
    return "finding";
  }

  if (/^\[chore\]/i.test(title)) {
    return "chore";
  }

  return null;
}

function taskEpicLink(item) {
  if (item.parent_issue_url) {
    return { linked: true };
  }

  // Accept exactly one reference to this repository; anything else stays a
  // missing link rather than guessing which issue was meant.
  const value = getSectionWithPresence(item.body || "", epicSectionHeadings).value;
  const url = `https://github.com/${repo}/issues/`;
  const match = /^#(\d+)$/.exec(value)
    || (value.toLowerCase().startsWith(url.toLowerCase()) && /^(\d+)$/.exec(value.slice(url.length)));
  const number = match ? Number(match[1]) : null;

  return { linked: false, number: number && number !== item.number ? number : null };
}

function linkToEpic(item, epicNumber) {
  const epic = runGh(["api", `repos/${repo}/issues/${epicNumber}`], {
    capture: true,
    allowFailure: true,
  });
  if (epic.status !== 0) {
    return false;
  }

  const target = JSON.parse(epic.stdout);
  const isEpic = getLabelNames(target).includes("kind:epic")
    || /^epic$/i.test(target.type?.name || "");
  if (target.pull_request || !isEpic) {
    console.log(`Issue #${item.number}: #${epicNumber} is not an epic. Kept needs:epic.`);
    return false;
  }

  const result = runGh([
    "api", "-X", "POST", `repos/${repo}/issues/${epicNumber}/sub_issues`,
    "-F", `sub_issue_id=${item.id}`,
  ], { allowFailure: true });
  return result.status === 0;
}

function hasHeading(body, heading) {
  return getSectionWithPresence(body, [heading]).found;
}

function getLabelNames(item) {
  return (item.labels || []).map((label) => label.name || label).filter(Boolean);
}

function addLabel(number, label) {
  runGh(["issue", "edit", String(number), "--repo", repo, "--add-label", label]);
}

function removeLabel(number, label) {
  runGh(["issue", "edit", String(number), "--repo", repo, "--remove-label", label]);
}

function addMissingEpicComment(number) {
  const existing = runGh([
    "api",
    `repos/${repo}/issues/${number}/comments`,
    "--paginate",
    "--jq",
    `.[] | select(.body | contains("${marker}")) | .id`,
  ], {
    capture: true,
    allowFailure: true,
  });

  if (existing.stdout.trim()) {
    return;
  }

  const body = [
    marker,
    "This development task needs a parent epic before it is ready for planning.",
    "",
    "Write the epic as `#123` in the `Parent epic` field, and automation adds this task as a sub-issue of that epic. You can also add the sub-issue relationship directly from the epic.",
  ].join("\n");

  runGh([
    "api",
    `repos/${repo}/issues/${number}/comments`,
    "-f",
    `body=${body}`,
  ], {
    allowFailure: true,
  });
}

function runGh(args, options = {}) {
  const printable = ["gh", ...args].join(" ");

  if (dryRun && !options.capture) {
    console.log(`[dry-run] ${printable}`);
    return { status: 0, stdout: "" };
  }

  const result = spawnSync("gh", args, {
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    env: process.env,
    timeout: 60_000,
    maxBuffer: 1024 * 1024,
  });

  const status = result.status ?? 1;

  if (status !== 0 && !options.allowFailure) {
    process.exit(status);
  }

  if (status !== 0 && options.capture && result.stderr) {
    process.stderr.write(result.stderr);
  }

  return {
    status,
    stdout: result.stdout || "",
  };
}

function runSelfTest() {
  const section = (value) => `## Parent epic\n${value}\n\n## Problem\nMentions #999.`;
  assert.deepEqual(taskEpicLink({ number: 5, body: section("#123") }), { linked: false, number: 123 });
  assert.deepEqual(
    taskEpicLink({ number: 5, body: section(`https://github.com/${repo}/issues/123`) }),
    { linked: false, number: 123 },
  );
  assert.deepEqual(
    taskEpicLink({ number: 5, body: section("") }),
    { linked: false, number: null },
    "an empty Parent epic field must not fall back to unrelated issue references",
  );
  assert.deepEqual(
    taskEpicLink({ number: 5, body: section("#5") }),
    { linked: false, number: null },
    "a task cannot be its own epic",
  );
  assert.deepEqual(
    taskEpicLink({ number: 5, body: section("https://github.com/other/repo/issues/123") }),
    { linked: false, number: null },
    "only epics in this repository can be linked automatically",
  );
  for (const value of ["#123 #456", "https://notgithub.com/eneo-ai/eneo/issues/123", "see #123"]) {
    assert.deepEqual(
      taskEpicLink({ number: 5, body: section(value.replace("eneo-ai/eneo", repo)) }),
      { linked: false, number: null },
      `ambiguous or foreign reference must not be linked: ${value}`,
    );
  }
  assert.deepEqual(
    taskEpicLink({ number: 5, body: "Legacy task. Parent #123." }),
    { linked: false, number: null },
    "a body without a Parent epic field is not a parent link",
  );
  assert.deepEqual(
    taskEpicLink({ number: 5, body: section(""), parent_issue_url: "https://api.github.com/repos/x/y/issues/1" }),
    { linked: true },
    "a native parent counts even when the form field is empty",
  );

  const pr = (overrides) => ({
    isDraft: false, baseRefName: "develop", labels: [], closingIssuesReferences: [], ...overrides,
  });
  const linked = { closingIssuesReferences: [{ number: 1013 }] };
  const labeled = { labels: [{ name: "needs:task-link" }] };
  assert.equal(taskLinkLabelChange(pr({}), "develop"), "add");
  assert.equal(taskLinkLabelChange(pr(labeled), "develop"), null);
  assert.equal(
    taskLinkLabelChange(pr({ ...linked, ...labeled }), "develop"),
    "remove",
    "a sidebar or keyword link reported by GitHub must clear the label",
  );
  assert.equal(taskLinkLabelChange(pr(linked), "develop"), null);
  assert.equal(taskLinkLabelChange(pr({ baseRefName: "release/v2.2" }), "develop"), null);
  assert.equal(
    taskLinkLabelChange(pr({ baseRefName: "release/v2.2", ...labeled }), "develop"),
    "remove",
    "retargeting away from the default branch must clear the label",
  );
  assert.equal(taskLinkLabelChange(pr({ isDraft: true }), "develop"), null);
  assert.equal(
    taskLinkLabelChange(pr({ isDraft: true, ...labeled }), "develop"),
    "remove",
    "converting a ready PR to draft must clear the label",
  );

  console.log("project-intake self-test passed");
}
