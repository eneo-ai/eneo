import type { HttpAuthoredConfig, HttpAuth, HttpMethod } from "./httpConfigTypes";

export function getHttpSummaryText(config: HttpAuthoredConfig | null | undefined, method: HttpMethod): string {
  if (!config || !config.url.trim()) return "";

  const parts: string[] = [];

  // Method
  parts.push(method);

  // Domain from URL
  try {
    const url = new URL(config.url.trim());
    parts.push(url.hostname);
  } catch {
    parts.push(config.url.trim().substring(0, 30));
  }

  // Auth mode
  parts.push(getAuthLabel(config.auth));

  // Body mode
  if (config.body.mode !== "none") {
    const bodyLabels: Record<string, string> = {
      auto: "JSON",
      json_template: "JSON",
      text_template: "Text",
    };
    const label = bodyLabels[config.body.mode];
    if (label) parts.push(label);
  }

  // Timeout
  parts.push(`${config.timeout_seconds}s`);

  return parts.join(" \u2022 ");
}

export function getAuthLabel(auth: HttpAuth): string {
  switch (auth.mode) {
    case "bearer_token": return "Bearer";
    case "api_key": return "API-nyckel";
    case "basic_auth": return "Basic";
    case "none": return "Ingen";
    default: return "Ingen";
  }
}

export function getAuthLabelEn(auth: HttpAuth): string {
  switch (auth.mode) {
    case "bearer_token": return "Bearer token";
    case "api_key": return "API key";
    case "basic_auth": return "Basic auth";
    case "none": return "None";
    default: return "None";
  }
}
