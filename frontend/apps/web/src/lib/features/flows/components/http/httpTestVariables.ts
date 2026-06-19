export type HttpTestVariablesParseResult =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false };

export function parseHttpTestVariables(raw: string): HttpTestVariablesParseResult {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true, value: {} };

  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (isJsonObject(parsed)) {
      return { ok: true, value: parsed };
    }
  } catch {
    return { ok: false };
  }

  return { ok: false };
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
