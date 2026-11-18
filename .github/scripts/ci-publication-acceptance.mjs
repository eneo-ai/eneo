// Decides whether image publication of a develop commit can reuse the merge queue's CI.
// It can only when a completed, successful merge_group run of this repository's ci.yml
// on exactly this commit left a validation receipt (written by CI after every required
// job passed) that names that run, its latest attempt and the full scope. Anything
// else, including an expired receipt, an API error or the deadline, runs the full
// checks; tags, manual runs and other branches always do.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const CI_WORKFLOW = ".github/workflows/ci.yml";
const DEADLINE_MS = 120_000;

/** Whether a run and the receipt it left prove the full suite passed on sha. */
export function proves(run, receipt, { sha, repository }) {
  return run.event === "merge_group"
    && run.path === CI_WORKFLOW
    && run.head_sha === sha
    && run.repository?.full_name === repository
    && run.head_repository?.full_name === repository
    && run.status === "completed"
    && run.conclusion === "success"
    && receipt?.schema === 1
    && receipt.sha === sha
    && receipt.repository === repository
    && receipt.workflow?.startsWith(`${repository}/${CI_WORKFLOW}@`)
    && receipt.event === "merge_group"
    && receipt.run_id === run.id
    && receipt.run_attempt === run.run_attempt
    && receipt.scope === "full";
}

async function api(route, signal) {
  const response = await fetch(`${process.env.GITHUB_API_URL ?? "https://api.github.com"}${route}`, {
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      "x-github-api-version": "2022-11-28",
    },
    signal,
  });
  if (!response.ok) throw new Error(`${route}: HTTP ${response.status}`);
  return response.json();
}

/** The receipt a run left, or undefined when it left none that is still kept. */
function receiptOf(repository, run, signal, deadline) {
  return api(`/repos/${repository}/actions/runs/${run.id}/artifacts?name=ci-receipt`, signal)
    .then(({ artifacts }) => {
      const kept = artifacts.filter((artifact) => !artifact.expired);
      if (kept.length !== 1) return undefined;
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ci-receipt-"));
      execFileSync("gh", ["run", "download", String(run.id), "--repo", repository, "--name", "ci-receipt", "--dir", directory], {
        stdio: ["ignore", "ignore", "inherit"],
        timeout: Math.max(1_000, deadline - Date.now()),
      });
      return JSON.parse(fs.readFileSync(path.join(directory, "ci-receipt.json"), "utf8"));
    });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { GITHUB_EVENT_NAME: event, GITHUB_REF: ref, GITHUB_SHA: sha, GITHUB_REPOSITORY: repository } = process.env;
  let reuse = false;
  let note = "full checks";
  if (event === "push" && ref === "refs/heads/develop") {
    const deadline = Date.now() + DEADLINE_MS;
    const signal = AbortSignal.timeout(DEADLINE_MS);
    try {
      const { workflow_runs: runs } = await api(
        `/repos/${repository}/actions/workflows/ci.yml/runs?event=merge_group&head_sha=${sha}&status=completed&per_page=20`,
        signal,
      );
      for (const run of runs.filter((candidate) => candidate.conclusion === "success")) {
        if (proves(run, await receiptOf(repository, run, signal, deadline), { sha, repository })) {
          reuse = true;
          note = `the full suite passed in merge-queue run ${run.id}, attempt ${run.run_attempt}`;
          break;
        }
      }
      if (!reuse) note = "no merge-queue run left a full-suite receipt for this commit; full checks";
    } catch (error) {
      console.log(`::warning::Cannot verify the merge queue's CI; full checks. ${error.message}`);
    }
  }
  console.log(note);
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `reuse=${reuse}\n`);
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `CI acceptance: ${note}.\n`);
}
