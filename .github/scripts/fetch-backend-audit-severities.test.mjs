import assert from "node:assert/strict";
import test from "node:test";
import { fetchSeverities } from "./fetch-backend-audit-severities.mjs";

const GHSA = "GHSA-6q48-6c7w-9gw2";
const OTHER = "GHSA-aaaa-bbbb-cccc";
const report = (...vulns) => ({
  dependencies: [{ name: "certifi", version: "1.0", vulns }],
});
const advisory = (id, severity) => Response.json({ ghsa_id: id, severity });

test("CVE/PYSEC IDs resolve through their GHSA aliases and share cached ratings", async () => {
  const requested = [];
  const result = await fetchSeverities(
    report(
      { id: "PYSEC-2026-4320", aliases: ["CVE-2026-0001", GHSA] },
      { id: "CVE-2026-0001", aliases: [GHSA] },
    ),
    {
      request: async (url) => {
        requested.push(url);
        return advisory(GHSA, "medium");
      },
    },
  );
  assert.deepEqual(result, {
    "PYSEC-2026-4320": "moderate",
    "CVE-2026-0001": "moderate",
  });
  assert.deepEqual(requested, [`https://api.github.com/advisories/${GHSA}`]);
});

test("the highest rating wins across aliases and repeated pip-audit IDs", async () => {
  const options = {
    request: async (url) =>
      advisory(url.split("/").at(-1), url.endsWith(OTHER) ? "critical" : "low"),
  };
  assert.deepEqual(
    await fetchSeverities(report({ id: GHSA, aliases: [OTHER] }), options),
    { [GHSA]: "critical" },
  );
  assert.deepEqual(
    await fetchSeverities(
      report(
        { id: "CVE-2026-0001", aliases: [GHSA] },
        { id: "CVE-2026-0001", aliases: [OTHER] },
      ),
      options,
    ),
    { "CVE-2026-0001": "critical" },
  );
});

test("unrated advisories and findings without a GHSA stay unknown", async () => {
  const result = await fetchSeverities(
    report({ id: "PYSEC-2026-4320", aliases: [] }, { id: GHSA, aliases: [] }),
    { request: async () => advisory(GHSA, null) },
  );
  assert.deepEqual(result, { "PYSEC-2026-4320": "unknown", [GHSA]: "unknown" });
});

test("a missing rating cannot hide behind a lower rated alias", async () => {
  const result = await fetchSeverities(report({ id: GHSA, aliases: [OTHER] }), {
    request: async (url) =>
      advisory(url.split("/").at(-1), url.endsWith(OTHER) ? null : "low"),
  });
  assert.equal(result[GHSA], "unknown");
});

test("API, timeout, malformed response and advisory mismatch errors cannot yield a passing rating", async () => {
  const requests = [
    async () => new Response("unavailable", { status: 503 }),
    async () => {
      throw new DOMException("Timed out", "TimeoutError");
    },
    async () => new Response("not json"),
    async () => advisory(OTHER, "low"),
  ];
  for (const request of requests)
    await assert.rejects(fetchSeverities(report({ id: GHSA }), { request }));
});

test("a clean report needs no advisory service", async () => {
  assert.deepEqual(
    await fetchSeverities(report(), {
      request: async () => {
        throw new Error("Unexpected lookup");
      },
    }),
    {},
  );
});
