import type { HttpAuthoredConfig, HttpDirection, HttpMethod } from "./httpConfigTypes";

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
