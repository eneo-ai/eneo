import assert from "node:assert/strict";
import test from "node:test";
import { LABELS, ISSUE_AREAS, evaluatePullRequest, issueLabelChanges } from "./label-policy.mjs";
import { mergeGroupPullRequests } from "./check-pr-labels.mjs";

test("PRs require explicit change and area classifications", () => {
  for (const labels of [[], ["needs:task-link"], ["kind:task", "frontend"], ["security"], ["accessibility", "frontend"], ["bug"], ["bug", "python:uv"]]) {
    assert.equal(evaluatePullRequest(labels).ok, false, labels.join(","));
  }
  for (const labels of [["bug", "backend"], ["enhancement", "frontend", "backend"], ["refactor", "frontend"], ["kind:chore", "ci"], ["dependencies", "github-actions"], ["dependencies", "devcontainer"], ["BUG", "Backend", "security", "breaking-change"]]) {
    assert.equal(evaluatePullRequest(labels).ok, true, labels.join(","));
  }
});

test("conflicting primary types fail; documentation can accompany one primary type", () => {
  assert.equal(evaluatePullRequest(["bug", "enhancement", "backend"]).ok, false);
  assert.equal(evaluatePullRequest(["refactor", "kind:chore", "frontend"]).ok, false);
  assert.equal(evaluatePullRequest(["bug", "documentation"]).changeType, "bug");
  assert.deepEqual(evaluatePullRequest(["documentation"]), {
    ok: true, changeType: "documentation", areas: ["documentation"], errors: [],
  });
  assert.equal(evaluatePullRequest(["bug", "backend", "needs:task-link"]).ok, true);
});

test("removing a required label makes the next validation fail", () => {
  assert.equal(evaluatePullRequest(["bug", "backend"]).ok, true);
  assert.equal(evaluatePullRequest(["backend"]).ok, false);
  assert.equal(evaluatePullRequest(["bug"]).ok, false);
});

test("issue forms apply each supported area and are idempotent", () => {
  for (const [area, label] of ISSUE_AREAS) {
    const body = `### Area\n\n${area}\n\n### Problem\nSomething`;
    assert.deepEqual(issueLabelChanges({ body, labels: ["kind:task"] }), { add: [label], remove: [] });
    assert.deepEqual(issueLabelChanges({ body, labels: ["kind:task", label] }), { add: [], remove: [] });
  }
});

test("changing a form's area removes the previous selection and preserves other labels", () => {
  const change = issueLabelChanges({
    body: "### Area\nFrontend", previousBody: "### Area\nBackend",
    labels: ["kind:task", "backend", "security", "needs:triage"],
  });
  assert.deepEqual(change, { add: ["frontend"], remove: ["backend"] });
});

test("unclassified issues stay visible for triage without inventing a type", () => {
  assert.deepEqual(issueLabelChanges({ body: "", labels: [] }), { add: ["needs:triage"], remove: [] });
  assert.deepEqual(issueLabelChanges({ body: "### Area\nOther", labels: ["kind:task"] }), { add: ["needs:triage"], remove: [] });
  assert.deepEqual(issueLabelChanges({ body: "### Area\nOther", previousBody: "### Area\nBackend", labels: ["kind:task", "backend"] }), { add: ["needs:triage"], remove: ["backend"] });
  assert.deepEqual(issueLabelChanges({ body: "", labels: ["bug", "backend", "needs:triage"] }), { add: [], remove: [] });
});

const entry = (number, base, head) => ({ pullRequest: { number }, baseCommit: { oid: base }, headCommit: head ? { oid: head } : null });
test("merge queue validation includes every PR in the actual candidate chain", () => {
  const entries = [entry(10, "base", "first"), entry(11, "first", "second"), entry(12, "second", "third"), entry(13, "third", null)];
  assert.deepEqual(mergeGroupPullRequests({ base_sha: "base", head_sha: "second" }, entries), [10, 11]);
  assert.deepEqual(mergeGroupPullRequests({ base_sha: "first", head_sha: "third" }, entries), [11, 12]);
});

test("unknown, incomplete, empty, and cyclic merge groups fail closed", () => {
  assert.throws(() => mergeGroupPullRequests({ base_sha: "base", head_sha: "missing" }, []));
  assert.throws(() => mergeGroupPullRequests({ base_sha: "base", head_sha: "second" }, [entry(11, "first", "second")]));
  assert.throws(() => mergeGroupPullRequests({ base_sha: "base", head_sha: "base" }, []));
  assert.throws(() => mergeGroupPullRequests({ base_sha: "base", head_sha: "loop" }, [entry(11, "loop", "loop")]));
});

test("the catalog creates every label used by policy and issue area mapping", () => {
  const names = LABELS.map((label) => label.name);
  assert.equal(new Set(names).size, names.length);
  for (const label of ISSUE_AREAS.values()) assert.ok(names.includes(label));
  for (const label of LABELS) assert.match(label.color, /^[0-9a-f]{6}$/i);
});
