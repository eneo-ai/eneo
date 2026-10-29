import assert from "node:assert/strict";
import test from "node:test";
import { evaluate } from "./audit-dependencies.mjs";

const NOW = new Date("2026-10-21T12:00:00Z");
const advisory = (severity, overrides = {}) => ({
  severity,
  url: "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
  vulnerable_versions: "<2.0.0",
  ...overrides,
});

for (const severity of ["low", "moderate", "medium", "high", "critical"]) {
  test(`${severity} uses the same high threshold in the frontend`, () => {
    const result = evaluate({ example: [advisory(severity)] }, NOW);
    const blocks = ["high", "critical"].includes(severity);
    assert.equal(result.errors.length, blocks ? 1 : 0);
    assert.equal(result.warnings.length, blocks ? 0 : 1);
  });
}

test("warnings stay visible alongside blocking advisories", () => {
  const result = evaluate(
    { example: [advisory("low"), advisory("moderate"), advisory("critical")] },
    NOW,
  );
  assert.equal(result.errors.length, 1);
  assert.equal(result.warnings.length, 2);
  assert.match(result.errors[0], /example: critical/);
});

test("the release's low KaTeX advisory uses the shared warning policy", () => {
  const result = evaluate(
    {
      katex: [
        advisory("low", {
          url: "https://github.com/advisories/GHSA-238p-pmpm-9mq7",
          vulnerable_versions: "<0.18.2",
        }),
      ],
    },
    NOW,
  );
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.accepted, []);
  assert.match(result.warnings[0], /katex: low/);
});

test("a clean report passes", () => {
  assert.deepEqual(evaluate({}, NOW), {
    errors: [],
    warnings: [],
    accepted: [],
  });
});

test("missing and unsupported severity cannot be downgraded to warnings", () => {
  for (const severity of [undefined, null, "", "unknown", "severe"]) {
    assert.equal(
      evaluate({ example: [advisory(severity)] }, NOW).errors.length,
      1,
    );
  }
});

test("an exception matches only its advisory, package and vulnerable range", () => {
  const accepted = advisory("high", {
    url: "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
    vulnerable_versions: "<=3.0.3",
  });
  assert.equal(evaluate({ braces: [accepted] }, NOW).accepted.length, 1);
  for (const report of [
    { other: [accepted] },
    { braces: [{ ...accepted, vulnerable_versions: "<=4.0.0" }] },
    {
      braces: [
        {
          ...accepted,
          url: "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
        },
      ],
    },
  ])
    assert.equal(evaluate(report, NOW).errors.length, 1);
});

test("expired exceptions still fail when the finding is absent or below high", () => {
  const expired = new Date("2026-11-05T00:00:00Z");
  for (const report of [{}, { example: [advisory("low")] }]) {
    assert.match(
      evaluate(report, expired).errors[0],
      /Review braces.*before 2026-11-05/,
    );
  }
});

test("malformed reports fail instead of reporting a clean audit", () => {
  for (const report of [
    null,
    [],
    "clean",
    { example: {} },
    { example: [null] },
  ]) {
    assert.throws(() => evaluate(report, NOW));
  }
});
