#!/usr/bin/env node

import fs from "node:fs";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const dryRun = process.argv.includes("--dry-run");
const selfTest = process.argv.includes("--self-test");
const marker = "<!-- eneo-project-intake:missing-epic -->";
const repo = process.env.GITHUB_REPOSITORY || "eneo-ai/eneo";
const eventPath = process.env.GITHUB_EVENT_PATH;

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
  await handleIssue(issue);
} else {
  await handlePullRequest(pullRequest);
}

async function handleIssue(item) {
  const labels = getLabelNames(item);
  const kind = inferIssueKind(item, labels);

  if (kind) {
    addLabel(item.number, `kind:${kind}`);
  }

  if (kind !== "task") {
    return;
  }

  if (hasEpicReference(item.body || "")) {
    removeLabel(item.number, "needs:epic");
    return;
  }

  addLabel(item.number, "needs:epic");
  addMissingEpicComment(item.number);
}

async function handlePullRequest(item) {
  if (item.draft) {
    return;
  }

  const text = `${item.title || ""}\n${item.body || ""}`;

  if (hasClosingIssueReference(text)) {
    removeLabel(item.number, "needs:task-link");
    return;
  }

  addLabel(item.number, "needs:task-link");
  console.log(
    `PR #${item.number} has no linked development task. Added needs:task-link.`,
  );
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

function hasEpicReference(body) {
  const parentEpicSection = getSectionWithPresence(body, [
    "Parent epic",
    "Epic",
    "Parent issue",
  ]);

  if (parentEpicSection.found) {
    return hasIssueReference(parentEpicSection.value);
  }

  return hasIssueReference(body);
}

function hasIssueReference(value) {
  return /(^|\s)#\d+\b/.test(value)
    || /github\.com\/[^/\s]+\/[^/\s]+\/issues\/\d+/i.test(value);
}

function hasClosingIssueReference(value) {
  const keyword = String.raw`\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)`;
  const issueReference = [
    String.raw`#\d+`,
    String.raw`[^/\s]+\/[^/\s]+#\d+`,
    String.raw`https?:\/\/github\.com\/[^/\s]+\/[^/\s]+\/issues\/\d+`,
  ].join("|");
  const pattern = new RegExp(`${keyword}:?\\s+(?:${issueReference})\\b`, "i");

  return pattern.test(value);
}

function hasHeading(body, heading) {
  const escaped = escapeRegExp(heading);
  return new RegExp(`^#{2,6}\\s+${escaped}\\s*$`, "im").test(body);
}

function getSectionWithPresence(body, headings) {
  for (const heading of headings) {
    const escaped = escapeRegExp(heading);
    const pattern = new RegExp(
      `^#{2,6}\\s+${escaped}\\s*$([\\s\\S]*?)(?=^#{2,6}\\s+|$(?![\\s\\S]))`,
      "im",
    );
    const match = body.match(pattern);

    if (match) {
      return {
        found: true,
        value: match[1].trim(),
      };
    }
  }

  return {
    found: false,
    value: "",
  };
}

function getLabelNames(item) {
  return (item.labels || []).map((label) => label.name || label).filter(Boolean);
}

function addLabel(number, label) {
  runGh(["issue", "edit", String(number), "--repo", repo, "--add-label", label], {
    allowFailure: true,
  });
}

function removeLabel(number, label) {
  runGh(["issue", "edit", String(number), "--repo", repo, "--remove-label", label], {
    allowFailure: true,
  });
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
    "Add the epic as a GitHub sub-issue relationship when available, and keep the `Parent epic` field in the issue body as `#123` so roadmap exports can resolve it.",
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

  if (dryRun) {
    console.log(`[dry-run] ${printable}`);
    return { status: 0, stdout: "" };
  }

  const result = spawnSync("gh", args, {
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    env: process.env,
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

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function runSelfTest() {
  assert.equal(
    hasEpicReference([
      "## Parent epic",
      "",
      "## Problem",
      "This mentions #999 but has no parent epic.",
    ].join("\n")),
    false,
    "empty Parent epic section must not fall back to unrelated issue references",
  );

  assert.equal(
    hasEpicReference([
      "## Parent epic",
      "#123",
      "",
      "## Problem",
      "Implement the scoped work.",
    ].join("\n")),
    true,
    "Parent epic section with an issue reference should be valid",
  );

  assert.equal(
    hasEpicReference("Legacy task created before the form existed. Parent #123."),
    true,
    "legacy unstructured task bodies should keep the issue-reference fallback",
  );

  assert.equal(hasClosingIssueReference("fixes #123"), true);
  assert.equal(hasClosingIssueReference("Closes: #123"), true);
  assert.equal(
    hasClosingIssueReference("Resolves https://github.com/eneo-ai/eneo/issues/123"),
    true,
  );
  assert.equal(hasClosingIssueReference("Fixes: eneo-ai/eneo#123"), true);
  assert.equal(
    hasClosingIssueReference("This PR implements #123"),
    false,
    "generic issue mentions should not count as task-closing references",
  );

  console.log("project-intake self-test passed");
}
