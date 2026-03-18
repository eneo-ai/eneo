import type { HttpAuthoredConfig, HttpDirection, HttpMethod, HttpAuth, HttpBody, CustomHeader } from "./httpConfigTypes";
import { isSecretSentinel } from "./httpConfigTypes";

export function createDefaultHttpConfig(direction: HttpDirection, method: HttpMethod): HttpAuthoredConfig {
  return {
    url: "",
    auth: { mode: "none" },
    timeout_seconds: 30,
    body: { mode: direction === "output" ? "auto" : "none" },
    custom_headers: [],
    response_format: direction === "input" ? "text" : null,
  };
}

export interface HttpValidationError {
  field: string;
  code: string;
  message: string;
}

export function validateHttpConfig(
  config: HttpAuthoredConfig,
  direction: HttpDirection,
  method: HttpMethod,
): HttpValidationError[] {
  const errors: HttpValidationError[] = [];

  // URL required
  if (!config.url.trim()) {
    errors.push({ field: "url", code: "HTTP_MISSING_URL", message: "" });
  } else {
    try {
      const parsed = new URL(config.url.trim());
      if (!["http:", "https:"].includes(parsed.protocol)) {
        errors.push({ field: "url", code: "HTTP_INVALID_URL", message: "" });
      }
    } catch {
      errors.push({ field: "url", code: "HTTP_INVALID_URL", message: "" });
    }
  }

  // Auth credentials (skip sentinel)
  if (config.auth.mode === "bearer_token") {
    const token = (config.auth as any).token;
    if (!token && !isSecretSentinel(token)) {
      errors.push({ field: "auth", code: "HTTP_MISSING_AUTH", message: "" });
    }
  } else if (config.auth.mode === "api_key") {
    const key = (config.auth as any).key;
    if (!key && !isSecretSentinel(key)) {
      errors.push({ field: "auth", code: "HTTP_MISSING_AUTH", message: "" });
    }
  } else if (config.auth.mode === "basic_auth") {
    const auth = config.auth as any;
    if (!auth.username && !auth.password && !isSecretSentinel(auth.password)) {
      errors.push({ field: "auth", code: "HTTP_MISSING_AUTH", message: "" });
    }
  }

  // Body: GET cannot have body template
  if (method === "GET" && config.body.mode !== "none" && config.body.mode !== "auto") {
    errors.push({ field: "body", code: "HTTP_BODY_NOT_ALLOWED_FOR_GET", message: "" });
  }

  // JSON template must be valid JSON (allow template expressions)
  if (config.body.mode === "json_template" && config.body.template) {
    try {
      JSON.parse(config.body.template);
    } catch {
      if (!config.body.template.includes("{{")) {
        errors.push({ field: "body", code: "HTTP_INVALID_BODY_JSON", message: "" });
      }
    }
  }

  // Timeout range
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
