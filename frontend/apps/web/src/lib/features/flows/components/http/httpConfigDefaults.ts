import type { HttpAuthoredConfig, HttpDirection, HttpMethod } from "./httpConfigTypes";
import { isSecretSentinel } from "./httpConfigTypes";

export function createDefaultHttpConfig(
  direction: HttpDirection,
  _method: HttpMethod
): HttpAuthoredConfig {
  return {
    url: "",
    auth: { mode: "none" },
    timeout_seconds: 30,
    body: { mode: direction === "output" ? "auto" : "none" },
    custom_headers: [],
    response_format: direction === "input" ? "text" : null
  };
}

export interface HttpValidationError {
  field: string;
  code: string;
  message: string;
}

export type HttpUrlValidationCode = "HTTP_MISSING_URL" | "HTTP_INVALID_URL";

const LITERAL_SCHEME_RE = /^[A-Za-z][A-Za-z0-9+.-]*:/;

function containsUrlUserinfo(url: string): boolean {
  const schemeSeparator = url.indexOf("://");
  if (schemeSeparator === -1) return false;
  let authority = url.slice(schemeSeparator + "://".length);
  for (const terminator of ["/", "?", "#"]) {
    const end = authority.indexOf(terminator);
    if (end !== -1) authority = authority.slice(0, end);
  }
  return authority.includes("@");
}

export function getAuthoredHttpUrlError(url: string): HttpUrlValidationCode | null {
  const trimmed = url.trim();
  if (!trimmed) return "HTTP_MISSING_URL";

  const schemeMatch = LITERAL_SCHEME_RE.exec(trimmed);
  if (schemeMatch && !["http:", "https:"].includes(schemeMatch[0].toLowerCase())) {
    return "HTTP_INVALID_URL";
  }

  // Userinfo puts a credential in a plain URL field, outside the auth fields the
  // backend encrypts. It is authored literally even when the host is a template,
  // so it is checked before templates defer the rest. The backend refuses it too.
  if (containsUrlUserinfo(trimmed)) return "HTTP_INVALID_URL";

  // Template URLs are validated after backend interpolation; literal non-HTTP schemes stay invalid above.
  if (trimmed.includes("{{")) return null;

  try {
    const parsed = new URL(trimmed);
    return ["http:", "https:"].includes(parsed.protocol) ? null : "HTTP_INVALID_URL";
  } catch {
    return "HTTP_INVALID_URL";
  }
}

export function validateHttpConfig(
  config: HttpAuthoredConfig,
  direction: HttpDirection,
  method: HttpMethod
): HttpValidationError[] {
  const errors: HttpValidationError[] = [];

  const urlError = getAuthoredHttpUrlError(config.url);
  if (urlError) {
    errors.push({ field: "url", code: urlError, message: "" });
  }

  if (config.auth.mode === "bearer_token") {
    const token = config.auth.token;
    if (!token && !isSecretSentinel(token)) {
      errors.push({ field: "auth", code: "HTTP_MISSING_AUTH", message: "" });
    }
  } else if (config.auth.mode === "api_key") {
    const key = config.auth.key;
    if (!key && !isSecretSentinel(key)) {
      errors.push({ field: "auth", code: "HTTP_MISSING_AUTH", message: "" });
    }
  } else if (config.auth.mode === "basic_auth") {
    if (!config.auth.username && !config.auth.password && !isSecretSentinel(config.auth.password)) {
      errors.push({ field: "auth", code: "HTTP_MISSING_AUTH", message: "" });
    }
  }

  if (method === "GET" && config.body.mode !== "none" && config.body.mode !== "auto") {
    errors.push({ field: "body", code: "HTTP_BODY_NOT_ALLOWED_FOR_GET", message: "" });
  }

  if (config.body.mode === "json_template" && config.body.template) {
    try {
      JSON.parse(config.body.template);
    } catch {
      if (!config.body.template.includes("{{")) {
        errors.push({ field: "body", code: "HTTP_INVALID_BODY_JSON", message: "" });
      }
    }
  }

  if (config.timeout_seconds < 1 || config.timeout_seconds > 120) {
    errors.push({ field: "timeout", code: "HTTP_TIMEOUT_OUT_OF_RANGE", message: "" });
  }

  return errors;
}

// Check if an authored config has meaningful content beyond defaults
export function isHttpConfigured(config: HttpAuthoredConfig | null | undefined): boolean {
  if (!config) return false;
  return config.url.trim().length > 0;
}
