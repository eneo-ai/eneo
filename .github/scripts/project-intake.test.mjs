import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("project-intake.mjs", import.meta.url));

// Runs the real script against a fake `gh` that answers by argument prefix
// and records every call, so the GitHub writes themselves are asserted.
function runIntake(event, responses) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "intake-"));
  const log = path.join(dir, "calls.log");
  fs.writeFileSync(path.join(dir, "gh"), `#!/usr/bin/env node
const fs = require("node:fs");
const args = process.argv.slice(2).join(" ");
fs.appendFileSync(${JSON.stringify(log)}, args + "\\n");
const hit = ${JSON.stringify(responses)}.find((r) => args.startsWith(r.args));
if (hit?.stdout) process.stdout.write(JSON.stringify(hit.stdout));
process.exit(hit?.status ?? 0);
`, { mode: 0o755 });
  fs.writeFileSync(path.join(dir, "event.json"), JSON.stringify(event));
  const result = spawnSync(process.execPath, [script], {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${dir}${path.delimiter}${process.env.PATH}`,
      GITHUB_EVENT_PATH: path.join(dir, "event.json"),
      GITHUB_REPOSITORY: "eneo-ai/eneo",
    },
  });
  const calls = fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split("\n") : [];
  return { status: result.status, calls };
}

const task = (overrides) => ({
  id: 9001,
  number: 7,
  title: "[Task]: work",
  body: "### Parent epic\n\n#545\n\n### Area\n\nBackend",
  labels: [{ name: "kind:task" }, { name: "backend" }, { name: "needs:epic" }],
  ...overrides,
});
const epic = { number: 545, labels: [{ name: "kind:epic" }] };
const issueEvent = { issue: { number: 7 } };
const noComments = { args: "api repos/eneo-ai/eneo/issues/7/comments" };
const addsNeedsEpic = (calls) => calls.some((c) => c.includes("--add-label needs:epic"));

test("links a task to the epic named in Parent epic and clears needs:epic", () => {
  const { status, calls } = runIntake(issueEvent, [
    { args: "api repos/eneo-ai/eneo/issues/7", stdout: task() },
    { args: "api repos/eneo-ai/eneo/issues/545", stdout: epic },
  ]);
  assert.equal(status, 0);
  assert.ok(calls.includes("api -X POST repos/eneo-ai/eneo/issues/545/sub_issues -F sub_issue_id=9001"));
  assert.ok(calls.some((c) => c.includes("--remove-label needs:epic")));
});

test("keeps needs:epic when creating the sub-issue fails", () => {
  const { calls } = runIntake(issueEvent, [
    noComments,
    { args: "api repos/eneo-ai/eneo/issues/7", stdout: task() },
    { args: "api repos/eneo-ai/eneo/issues/545", stdout: epic },
    { args: "api -X POST", status: 1 },
  ]);
  assert.ok(!calls.some((c) => c.includes("--remove-label needs:epic")));
  assert.ok(addsNeedsEpic(calls));
});

test("does not link to an issue that is not an epic", () => {
  const { calls } = runIntake(issueEvent, [
    noComments,
    { args: "api repos/eneo-ai/eneo/issues/7", stdout: task() },
    { args: "api repos/eneo-ai/eneo/issues/545", stdout: { number: 545, labels: [] } },
  ]);
  assert.ok(!calls.some((c) => c.includes("sub_issues")));
  assert.ok(addsNeedsEpic(calls));
});

const withParent = task({ parent_issue_url: "https://api.github.com/repos/eneo-ai/eneo/issues/1" });

test("an existing epic parent clears needs:epic without a new link", () => {
  const { calls } = runIntake(issueEvent, [
    { args: "api repos/eneo-ai/eneo/issues/7", stdout: withParent },
    { args: "api repos/eneo-ai/eneo/issues/1", stdout: { number: 1, labels: [{ name: "kind:epic" }] } },
  ]);
  assert.ok(!calls.some((c) => c.includes("sub_issues")));
  assert.ok(calls.some((c) => c.includes("--remove-label needs:epic")));
});

test("a non-epic parent keeps needs:epic and is never replaced", () => {
  const { calls } = runIntake(issueEvent, [
    noComments,
    { args: "api repos/eneo-ai/eneo/issues/7", stdout: withParent },
    { args: "api repos/eneo-ai/eneo/issues/1", stdout: { number: 1, labels: [{ name: "bug" }] } },
    { args: "api repos/eneo-ai/eneo/issues/545", stdout: epic },
  ]);
  assert.ok(!calls.some((c) => c.includes("sub_issues")), "the body's epic must not replace the parent");
  assert.ok(!calls.some((c) => c.includes("--remove-label needs:epic")));
  assert.ok(addsNeedsEpic(calls));
});

test("uses live PR links, not the webhook payload", () => {
  const { calls } = runIntake(
    { pull_request: { number: 1014, body: "no link here", draft: false } },
    [{
      args: "pr view 1014",
      stdout: {
        isDraft: false,
        baseRefName: "develop",
        labels: [{ name: "needs:task-link" }],
        closingIssuesReferences: [{ number: 1013 }],
      },
    }],
  );
  assert.ok(calls.includes("issue edit 1014 --repo eneo-ai/eneo --remove-label needs:task-link"));
});

test("fails the run when a label cannot be removed", () => {
  const { status } = runIntake(
    { pull_request: { number: 1014 } },
    [
      {
        args: "pr view 1014",
        stdout: {
          isDraft: false,
          baseRefName: "release/v2.2",
          labels: [{ name: "needs:task-link" }],
          closingIssuesReferences: [],
        },
      },
      { args: "issue edit 1014", status: 1 },
    ],
  );
  assert.notEqual(status, 0);
});
