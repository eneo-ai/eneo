import { appendFileSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { blocksOnSeverity, normalizeSeverity } from "./dependency-audit-severity.mjs";

export const DEFAULT_EXCEPTIONS = fileURLToPath(
  new URL("../security/backend-audit-exceptions.json", import.meta.url),
);

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const normalizeName = (name) => String(name).toLowerCase().replace(/[-_.]+/g, "-");

function expiryInstant(value) {
  if (!ISO_DATE.test(value)) return null;
  const instant = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(instant.getTime()) || instant.toISOString().slice(0, 10) !== value
    ? null
    : instant;
}

export function parseExceptions(raw) {
  const errors = [];
  const entries = [];
  if (!Array.isArray(raw?.exceptions)) {
    return { entries, errors: ['The exceptions file must contain an "exceptions" array.'] };
  }
  raw.exceptions.forEach((item, index) => {
    const where = `exceptions[${index}]${item?.id ? ` (${item.id})` : ""}`;
    const missing = ["id", "package", "rationale", "expires"].filter(
      (key) => typeof item?.[key] !== "string" || item[key].trim() === "",
    );
    if (missing.length > 0) {
      errors.push(`${where}: missing ${missing.join(", ")}.`);
      return;
    }
    const expires = expiryInstant(item.expires);
    if (!expires) {
      errors.push(`${where}: "expires" must be a valid ISO date (YYYY-MM-DD), got "${item.expires}".`);
      return;
    }
    entries.push({
      id: item.id.trim(),
      package: normalizeName(item.package),
      rationale: item.rationale.trim(),
      expires: item.expires,
      expiresAt: expires,
    });
  });
  return { entries, errors };
}

export function parseReport(raw) {
  if (!Array.isArray(raw?.dependencies)) {
    throw new Error('The pip-audit report has no "dependencies" array; pip-audit probably failed before auditing.');
  }
  const findings = [];
  for (const dependency of raw.dependencies) {
    if (typeof dependency?.name !== "string" || typeof dependency.version !== "string" || !Array.isArray(dependency.vulns)) {
      throw new Error(`Incomplete pip-audit result for ${dependency?.name ?? "unknown package"}: ${dependency?.skip_reason ?? "missing package version or vulnerabilities"}.`);
    }
    for (const vuln of dependency.vulns) {
      if (typeof vuln?.id !== "string" || !Array.isArray(vuln.aliases ?? []) || !Array.isArray(vuln.fix_versions ?? [])) {
        throw new Error(`Invalid pip-audit advisory for ${dependency.name}.`);
      }
      findings.push({
        package: dependency.name,
        version: dependency.version,
        id: vuln.id,
        aliases: vuln.aliases ?? [],
        fixVersions: vuln.fix_versions ?? [],
      });
    }
  }
  return findings;
}

// Expiry is the start of the listed day in UTC, like the frontend audit exceptions.
export function evaluate(report, severities, exceptionsFile, now = new Date()) {
  if (!severities || typeof severities !== "object" || Array.isArray(severities)) {
    throw new Error("The advisory severities must be an object keyed by pip-audit advisory ID.");
  }
  const { entries, errors: configErrors } = parseExceptions(exceptionsFile);
  const findings = parseReport(report);
  const exceptionProblems = [...configErrors];
  const errors = [];
  const warnings = [];
  const matched = new Set();
  const rows = [];

  for (const entry of entries) {
    if (now >= entry.expiresAt) {
      exceptionProblems.push(
        `Exception ${entry.id} for ${entry.package} expired on ${entry.expires}. Bump the dependency or renew the exception with a new rationale and date.`,
      );
    }
  }

  for (const finding of findings) {
    const name = normalizeName(finding.package);
    const ids = new Set([finding.id, ...finding.aliases]);
    const severity = normalizeSeverity(severities[finding.id]);
    const entry = entries.find((candidate) => candidate.package === name && ids.has(candidate.id));
    const label = `${finding.package} ${finding.version} ${finding.id}`;
    const row = { ...finding, severity: severity ?? "unknown", status: "", note: "" };

    if (entry && now < entry.expiresAt) {
      matched.add(entry);
      row.status = "Excepted";
      row.note = `Until ${entry.expires}: ${entry.rationale}`;
    } else if (!severity || blocksOnSeverity(severity)) {
      if (entry) matched.add(entry);
      row.status = "Blocking";
      row.note = !severity
        ? "Severity unavailable; review the advisory before allowing it."
        : finding.fixVersions.length > 0
          ? `Upgrade to ${finding.fixVersions.join(" or ")}.`
          : "No fixed version yet; requires a reviewed, time-limited exception.";
      if (entry) row.note = `Exception expired ${entry.expires}. ${row.note}`;
      errors.push(`${label}: ${row.severity}. ${row.note}`);
    } else {
      row.status = "Warning";
      row.note = finding.fixVersions.length > 0
        ? `Upgrade to ${finding.fixVersions.join(" or ")}; below the high threshold.`
        : "No fixed version yet; below the high threshold.";
      warnings.push(`${label}: ${severity}. ${row.note}`);
    }
    rows.push(row);
  }

  for (const entry of entries) {
    if (!matched.has(entry) && now < entry.expiresAt) {
      warnings.push(`Exception ${entry.id} for ${entry.package} no longer matches a finding; remove it.`);
    }
  }

  return { rows, errors: [...exceptionProblems, ...errors], exceptionProblems, warnings };
}

const cell = (value) => String(value).replaceAll("|", "\\|").replaceAll("\n", " ");

export function summarize({ rows, exceptionProblems }) {
  const lines = ["### Backend dependency audit", ""];
  if (rows.length === 0) {
    lines.push("No known vulnerabilities in the backend runtime lock.");
  } else {
    lines.push("| Status | Severity | Package | Installed | Advisory | Fixed in | Note |", "| --- | --- | --- | --- | --- | --- | --- |");
    for (const row of rows) {
      const advisory = [row.id, ...row.aliases].join(", ");
      lines.push(
        `| ${cell(row.status)} | ${cell(row.severity)} | ${cell(row.package)} | ${cell(row.version)} | ${cell(advisory)} | ${cell(row.fixVersions.join(", ") || "-")} | ${cell(row.note)} |`,
      );
    }
  }
  const count = (status) => rows.filter((row) => row.status === status).length;
  lines.push("", `${count("Blocking")} blocking, ${count("Excepted")} excepted, ${count("Warning")} warnings.`);
  if (exceptionProblems.length > 0) {
    lines.push("", "Exception problems:", ...exceptionProblems.map((problem) => `- ${problem}`));
  }
  return lines.join("\n") + "\n";
}

const escapeAnnotation = (message) =>
  message.replaceAll("%", "%25").replaceAll("\r", "%0D").replaceAll("\n", "%0A");

export function run(argv, env = process.env, now = new Date()) {
  const [auditPath, severitiesPath, exceptionsPath = DEFAULT_EXCEPTIONS] = argv;
  if (!auditPath || !severitiesPath) {
    console.error("Usage: evaluate-backend-audit.mjs <pip-audit.json> <severities.json> [exceptions.json]");
    return 2;
  }
  let result;
  try {
    result = evaluate(
      JSON.parse(readFileSync(auditPath, "utf8")),
      JSON.parse(readFileSync(severitiesPath, "utf8")),
      JSON.parse(readFileSync(exceptionsPath, "utf8")),
      now,
    );
  } catch (error) {
    console.log(`::error::Backend audit could not be evaluated: ${escapeAnnotation(error.message)}`);
    return 2;
  }
  for (const message of result.warnings) console.log(`::warning::${escapeAnnotation(message)}`);
  for (const message of result.errors) console.log(`::error::${escapeAnnotation(message)}`);
  const summary = summarize(result);
  console.log(summary);
  if (env.GITHUB_STEP_SUMMARY) appendFileSync(env.GITHUB_STEP_SUMMARY, summary);
  return result.errors.length > 0 ? 1 : 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exitCode = run(process.argv.slice(2));
}
