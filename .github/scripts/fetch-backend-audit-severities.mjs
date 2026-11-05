import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  highestSeverity,
  normalizeSeverity,
} from "./dependency-audit-severity.mjs";
import { parseReport } from "./evaluate-backend-audit.mjs";

const GHSA = /^GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$/i;

// pip-audit's JSON has advisory IDs and fixes, but no severity. Keep the
// fetched ratings as a separate artifact so the decision can be replayed.
export async function fetchSeverities(report, { token, request = fetch } = {}) {
  const cache = new Map();
  const severities = {};
  for (const finding of parseReport(report)) {
    const ids = [
      ...new Set(
        [finding.id, ...finding.aliases].filter((id) => GHSA.test(id)),
      ),
    ];
    const ratings = [];
    for (const id of ids) {
      if (!cache.has(id)) {
        const response = await request(
          `https://api.github.com/advisories/${id}`,
          {
            headers: {
              Accept: "application/vnd.github+json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            signal: AbortSignal.timeout(10_000),
            redirect: "error",
          },
        );
        if (!response.ok)
          throw new Error(
            `Severity lookup for ${id} failed: HTTP ${response.status}.`,
          );
        const advisory = await response.json();
        if (advisory.ghsa_id !== id)
          throw new Error(
            `Severity lookup returned a different advisory for ${id}.`,
          );
        cache.set(id, normalizeSeverity(advisory.severity) ?? "unknown");
      }
      ratings.push(cache.get(id));
    }
    // An unrated/PYSEC-only finding must be reviewed, never assumed low.
    if (severities[finding.id]) ratings.push(severities[finding.id]);
    severities[finding.id] = highestSeverity(ratings);
  }
  return severities;
}

export async function run(argv, env = process.env) {
  const [auditPath, outputPath] = argv;
  if (!auditPath || !outputPath) {
    console.error(
      "Usage: fetch-backend-audit-severities.mjs <pip-audit.json> <severities.json>",
    );
    return 2;
  }
  try {
    const report = JSON.parse(readFileSync(auditPath, "utf8"));
    const severities = await fetchSeverities(report, {
      token: env.GITHUB_TOKEN,
    });
    writeFileSync(outputPath, JSON.stringify(severities, null, 2) + "\n");
    return 0;
  } catch (error) {
    console.error(
      `::error::Backend advisory severities could not be loaded: ${error.message.replaceAll("%", "%25").replaceAll("\r", "%0D").replaceAll("\n", "%0A")}`,
    );
    return 2;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exitCode = await run(process.argv.slice(2));
}
