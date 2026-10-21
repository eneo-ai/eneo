import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { DEFAULT_EXCEPTIONS, evaluate, parseExceptions, summarize } from "./evaluate-backend-audit.mjs";

const script = fileURLToPath(new URL("./evaluate-backend-audit.mjs", import.meta.url));
const NOW = new Date("2026-10-21T12:00:00Z");

const vuln = (id, fix_versions, aliases = [], description = "Example advisory.") => ({
  id,
  fix_versions,
  aliases,
  description,
});
const report = (...dependencies) => ({ dependencies, fixes: [] });
const clean = { name: "httpx", version: "0.28.1", vulns: [] };
const fixable = {
  name: "certifi",
  version: "2026.6.17",
  vulns: [vuln("PYSEC-2026-4320", ["2026.10.19"], ["GHSA-6q48-6c7w-9gw2"])],
};
const unfixable = {
  name: "somepkg",
  version: "1.0.0",
  vulns: [vuln("GHSA-aaaa-bbbb-cccc", [], ["CVE-2026-0001"])],
};
const exception = (overrides = {}) => ({
  id: "GHSA-6q48-6c7w-9gw2",
  package: "certifi",
  rationale: "Lock bump blocked by an upstream pin.",
  expires: "2026-11-01",
  ...overrides,
});

test("a vulnerability with a fix version blocks", () => {
  const result = evaluate(report(clean, fixable), { exceptions: [] }, NOW);
  assert.equal(result.errors.length, 1);
  assert.match(result.errors[0], /certifi 2026\.6\.17 PYSEC-2026-4320 is fixable in 2026\.10\.19/);
  assert.deepEqual(result.rows.map((row) => row.status), ["Blocking"]);
});

test("a clean report passes with an empty summary table", () => {
  const result = evaluate(report(clean), { exceptions: [] }, NOW);
  assert.deepEqual([result.errors, result.warnings, result.rows], [[], [], []]);
  assert.match(summarize(result), /No known vulnerabilities/);
});

test("a vulnerability without a fix version only warns", () => {
  const result = evaluate(report(unfixable), { exceptions: [] }, NOW);
  assert.deepEqual(result.errors, []);
  assert.equal(result.warnings.length, 1);
  assert.match(result.warnings[0], /somepkg 1\.0\.0 GHSA-aaaa-bbbb-cccc has no fixed version/);
  assert.equal(result.rows[0].status, "No fix");
});

test("a listed, unexpired exception allows a fixable vulnerability, matched by id or alias", () => {
  for (const id of ["GHSA-6q48-6c7w-9gw2", "PYSEC-2026-4320"]) {
    const result = evaluate(report(fixable), { exceptions: [exception({ id })] }, NOW);
    assert.deepEqual(result.errors, [], id);
    assert.equal(result.rows[0].status, "Excepted");
    assert.match(result.rows[0].note, /Until 2026-11-01: Lock bump blocked/);
  }
});

test("an exception only covers its own package and advisory", () => {
  const otherPackage = evaluate(report(fixable), { exceptions: [exception({ package: "pillow" })] }, NOW);
  const otherId = evaluate(report(fixable), { exceptions: [exception({ id: "GHSA-0000-0000-0000" })] }, NOW);
  assert.equal(otherPackage.rows[0].status, "Blocking");
  assert.equal(otherId.rows[0].status, "Blocking");
  const normalized = evaluate(report({ ...fixable, name: "Cert_ifi" }), { exceptions: [exception({ package: "cert-ifi" })] }, NOW);
  assert.equal(normalized.rows[0].status, "Excepted");
});

test("an expired exception fails and names the id and date, even when it no longer matches", () => {
  const expired = exception({ expires: "2026-10-20" });
  const matching = evaluate(report(fixable), { exceptions: [expired] }, NOW);
  assert.ok(matching.errors.some((message) => message.includes("GHSA-6q48-6c7w-9gw2") && message.includes("2026-10-20")));
  assert.equal(matching.rows[0].status, "Blocking");
  assert.match(matching.rows[0].note, /expired 2026-10-20/);

  const unmatched = evaluate(report(clean), { exceptions: [expired] }, NOW);
  assert.equal(unmatched.errors.length, 1);
  assert.match(unmatched.errors[0], /GHSA-6q48-6c7w-9gw2.*expired on 2026-10-20/);
});

test("an exception expires at the start of its date in UTC", () => {
  const entry = exception({ expires: "2026-10-21" });
  assert.equal(evaluate(report(fixable), { exceptions: [entry] }, new Date("2026-10-20T23:59:59Z")).errors.length, 0);
  assert.ok(evaluate(report(fixable), { exceptions: [entry] }, new Date("2026-10-21T00:00:00Z")).errors.length > 0);
});

test("an unused, unexpired exception warns so it gets removed", () => {
  const result = evaluate(report(clean), { exceptions: [exception()] }, NOW);
  assert.deepEqual(result.errors, []);
  assert.match(result.warnings[0], /no longer matches a finding/);
});

test("malformed exception entries fail instead of silently allowing", () => {
  const bad = [
    { id: "GHSA-x", package: "certifi", expires: "2026-11-01" },
    exception({ expires: "next week" }),
    exception({ expires: "2026-02-30" }),
    exception({ rationale: "  " }),
  ];
  const { entries, errors } = parseExceptions({ exceptions: bad });
  assert.equal(entries.length, 0);
  assert.equal(errors.length, 4);
  assert.match(errors[0], /missing rationale/);
  assert.equal(parseExceptions({}).errors.length, 1);
  assert.ok(evaluate(report(fixable), { exceptions: bad }, NOW).errors.length >= 5);
});

test("a report without a dependencies array is rejected", () => {
  assert.throws(() => evaluate({}, { exceptions: [] }, NOW), /pip-audit probably failed/);
});

test("the summary table lists blocking, excepted and unfixable findings", () => {
  const result = evaluate(
    report(fixable, unfixable, {
      name: "pillow",
      version: "12.3.0",
      vulns: [vuln("CVE-2026-112895", ["13.0.0"], ["GHSA-p4wg-p73j-c528"])],
    }),
    { exceptions: [exception({ id: "GHSA-p4wg-p73j-c528", package: "pillow", rationale: "a | b" })] },
    NOW,
  );
  const summary = summarize(result);
  assert.match(summary, /\| Blocking \| certifi \| 2026\.6\.17 \| PYSEC-2026-4320, GHSA-6q48-6c7w-9gw2 \| 2026\.10\.19 \|/);
  assert.match(summary, /\| No fix \| somepkg \|/);
  assert.match(summary, /\| Excepted \| pillow \|.*a \\\| b/);
  assert.match(summary, /1 blocking, 1 excepted, 1 without a fix\./);
});

test("the checked-in exceptions file is valid and not expired", () => {
  const file = JSON.parse(readFileSync(DEFAULT_EXCEPTIONS, "utf8"));
  const { entries, errors } = parseExceptions(file);
  assert.deepEqual(errors, []);
  for (const entry of entries) {
    assert.ok(new Date() < entry.expiresAt, `${entry.id} expired on ${entry.expires}`);
  }
});

function cli(t, auditReport, exceptions) {
  const dir = mkdtempSync(join(tmpdir(), "eneo-backend-audit-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const audit = join(dir, "audit.json");
  const exceptionsPath = join(dir, "exceptions.json");
  const summary = join(dir, "summary.md");
  writeFileSync(audit, typeof auditReport === "string" ? auditReport : JSON.stringify(auditReport));
  writeFileSync(exceptionsPath, JSON.stringify({ exceptions }));
  const result = spawnSync(process.execPath, [script, audit, exceptionsPath], {
    encoding: "utf8",
    env: { ...process.env, GITHUB_STEP_SUMMARY: summary },
  });
  let written = "";
  try {
    written = readFileSync(summary, "utf8");
  } catch {}
  return { ...result, summary: written };
}

test("CLI: fixable vulnerability exits 1 with an error annotation and a summary", (t) => {
  const result = cli(t, report(fixable), []);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /^::error::certifi 2026\.6\.17 PYSEC-2026-4320 is fixable/m);
  assert.match(result.summary, /\| Blocking \| certifi \|/);
});

test("CLI: unfixable vulnerability exits 0 with a warning annotation and a summary", (t) => {
  const result = cli(t, report(clean, unfixable), []);
  assert.equal(result.status, 0);
  assert.match(result.stdout, /^::warning::somepkg 1\.0\.0 GHSA-aaaa-bbbb-cccc has no fixed version/m);
  assert.doesNotMatch(result.stdout, /::error::/);
  assert.match(result.summary, /\| No fix \| somepkg \|/);
});

test("CLI: a valid exception exits 0; the same exception once expired exits 1", (t) => {
  const allowed = cli(t, report(fixable), [exception({ expires: "2999-01-01" })]);
  assert.equal(allowed.status, 0);
  assert.match(allowed.summary, /\| Excepted \| certifi \|/);

  const expired = cli(t, report(fixable), [exception({ expires: "2000-01-01" })]);
  assert.equal(expired.status, 1);
  assert.match(expired.stdout, /::error::Exception GHSA-6q48-6c7w-9gw2 for certifi expired on 2000-01-01/);
});

test("CLI: a missing or unparsable report fails rather than passing", (t) => {
  const garbage = cli(t, "not json", []);
  assert.equal(garbage.status, 2);
  assert.match(garbage.stdout, /::error::Backend audit could not be evaluated/);
  assert.equal(spawnSync(process.execPath, [script, "/nonexistent/audit.json"], { encoding: "utf8" }).status, 2);
  assert.equal(spawnSync(process.execPath, [script], { encoding: "utf8" }).status, 2);
});
