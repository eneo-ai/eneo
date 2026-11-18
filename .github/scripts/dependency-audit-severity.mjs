// GitHub calls the middle band "medium"; Bun calls it "moderate".
const LEVELS = ["low", "moderate", "high", "critical"];

export function normalizeSeverity(value) {
  const level = typeof value === "string" ? value.toLowerCase() : "";
  const normalized = level === "medium" ? "moderate" : level;
  return LEVELS.includes(normalized) ? normalized : null;
}

export function blocksOnSeverity(value) {
  const severity = normalizeSeverity(value);
  if (!severity)
    throw new Error(`Missing or unsupported advisory severity: ${value}.`);
  return severity === "high" || severity === "critical";
}

export function highestSeverity(values) {
  if (values.length === 0 || values.some((value) => !normalizeSeverity(value)))
    return "unknown";
  return values
    .map(normalizeSeverity)
    .sort((a, b) => LEVELS.indexOf(b) - LEVELS.indexOf(a))[0];
}
