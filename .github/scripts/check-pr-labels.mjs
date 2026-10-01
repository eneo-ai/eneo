#!/usr/bin/env node

import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { evaluatePullRequest } from "./label-policy.mjs";

// Walk the actual candidate chain, not PR numbers parsed from a temporary
// branch name. A group can include more than one PR. Missing queue metadata
// is an error, never an exemption from the required check.
export function mergeGroupPullRequests(group, entries) {
  const byHead = new Map(entries.filter((entry) => entry.headCommit).map((entry) => [entry.headCommit.oid, entry]));
  const numbers = [];
  const visited = new Set();
  let sha = group.head_sha;
  while (sha !== group.base_sha) {
    const entry = byHead.get(sha);
    if (visited.has(sha) || !entry?.pullRequest?.number || !entry.baseCommit?.oid) {
      throw new Error("Cannot resolve every PR in this merge group. Rerun against the current merge queue.");
    }
    visited.add(sha);
    numbers.push(entry.pullRequest.number);
    sha = entry.baseCommit.oid;
  }
  if (numbers.length === 0) throw new Error("The merge group contains no pull requests.");
  return numbers.reverse();
}

function ghJson(args) {
  const result = spawnSync("gh", ["api", ...args], {
    encoding: "utf8", timeout: 60_000, maxBuffer: 4 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`GitHub metadata request failed: ${result.error?.message || result.stderr.trim()}`);
  }
  return JSON.parse(result.stdout);
}

function readMergeQueue(repo, group) {
  const [owner, name] = repo.split("/");
  const pages = ghJson([
    "graphql", "--paginate", "--slurp",
    "-f", `owner=${owner}`, "-f", `name=${name}`,
    "-f", `branch=${group.base_ref.replace(/^refs\/heads\//, "")}`,
    "-f", `query=query($owner: String!, $name: String!, $branch: String!, $endCursor: String) {
      repository(owner: $owner, name: $name) {
        mergeQueue(branch: $branch) {
          entries(first: 100, after: $endCursor) {
            nodes { headCommit { oid } baseCommit { oid } pullRequest { number } }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }`,
  ]);
  return pages.flatMap((page) => {
    if (page.errors || !page.data?.repository?.mergeQueue?.entries) {
      throw new Error("GitHub did not return the merge queue; classification cannot be verified.");
    }
    return page.data.repository.mergeQueue.entries.nodes;
  });
}

function main() {
  const repo = process.env.GITHUB_REPOSITORY || "eneo-ai/eneo";
  const args = process.argv.slice(2);
  let numbers;
  if (args.length === 2 && args[0] === "--pull-request" && /^[1-9]\d*$/.test(args[1])) {
    numbers = [Number(args[1])];
  } else if (args.length === 0 && process.env.GITHUB_EVENT_PATH) {
    const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
    if (event.pull_request?.number) numbers = [event.pull_request.number];
    else if (event.merge_group) numbers = mergeGroupPullRequests(event.merge_group, readMergeQueue(repo, event.merge_group));
    else throw new Error("Expected a pull request or merge_group event.");
  } else {
    throw new Error("Use GITHUB_EVENT_PATH or --pull-request <number>.");
  }

  const summaries = [];
  let ok = true;
  for (const number of numbers) {
    // Read live labels, including when someone reruns an older workflow.
    const pr = ghJson([`repos/${repo}/pulls/${number}`]);
    const result = evaluatePullRequest(pr.labels.map((label) => label.name));
    ok &&= result.ok;
    const message = result.ok
      ? `PR #${number}: ${result.changeType}; areas: ${result.areas.join(", ")}.`
      : `PR #${number}: ${result.errors.join(" ")} See .github/PROJECT_WORKFLOW.md#required-labels.`;
    console.log(result.ok ? message : `::error::${message}`);
    summaries.push(`- ${message}`);
  }
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summaries.join("\n")}\n`);
  return ok ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { process.exitCode = main(); }
  catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
