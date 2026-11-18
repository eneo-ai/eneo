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
  const expired = new Date("2026-12-15T00:00:00Z");
  for (const report of [{}, { example: [advisory("low")] }]) {
    assert.match(
      evaluate(report, expired).errors[0],
      /Review braces.*before 2026-12-15/,
    );
  }
});

test("a low deepmerge advisory stays a visible warning and high still blocks", () => {
  const after = new Date("2026-11-27T00:00:00Z");
  const deepmerge = (severity) => ({
    deepmerge: [
      advisory(severity, {
        url: "https://github.com/advisories/GHSA-gcqx-w48m-w2h4",
        vulnerable_versions: ">=4.2.0 <=4.3.1",
      }),
    ],
  });
  assert.deepEqual(evaluate(deepmerge("low"), after), {
    errors: [],
    warnings: [
      "deepmerge: low https://github.com/advisories/GHSA-gcqx-w48m-w2h4",
    ],
    accepted: [],
  });
  assert.equal(evaluate(deepmerge("high"), after).errors.length, 1);
});

const remoteFormDos = advisory("high", {
  url: "https://github.com/advisories/GHSA-3r8g-jcqq-3p5j",
  vulnerable_versions: ">=2.42.0 <=3.1.0",
});
const remoteFunctionsCheck = "scripts/remote-functions-off.test.mjs";

test("the remote functions form advisory is accepted only while its check passes", () => {
  const report = { "@sveltejs/kit": [remoteFormDos] };
  assert.equal(evaluate(report, NOW).accepted.length, 1);
  const failed = evaluate(report, NOW, [remoteFunctionsCheck]);
  assert.equal(failed.accepted.length, 0);
  assert.match(failed.errors.join("\n"), /@sveltejs\/kit: high .*GHSA-3r8g/);
  assert.match(
    failed.errors.join("\n"),
    /GHSA-3r8g.*remote-functions-off\.test\.mjs failed/,
  );
  assert.equal(
    evaluate(
      {
        "@sveltejs/kit": [
          { ...remoteFormDos, vulnerable_versions: ">=2.42.0 <=3.2.0" },
        ],
      },
      NOW,
    ).errors.length,
    1,
  );
});

test("the picomatch extglob advisory is accepted for its exact range only", () => {
  const extglob = advisory("high", {
    url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf",
    vulnerable_versions: "<=4.0.7",
  });
  assert.equal(evaluate({ picomatch: [extglob] }, NOW).accepted.length, 1);
  for (const report of [
    { picomatch: [{ ...extglob, vulnerable_versions: "<=4.0.8" }] },
    { micromatch: [extglob] },
  ])
    assert.equal(evaluate(report, NOW).errors.length, 1);
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
