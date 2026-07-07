export type LoginDiagnostics = {
  message?: string;
  info?: string;
  detailCode?: string;
  correlation?: string;
  rawDetail?: string;
};

const OIDC_FORBIDDEN_CODES = new Set(["access_denied", "forbidden", "oidc_forbidden"]);
const OIDC_UNAUTHORIZED_CODES = new Set(["unauthorized", "invalid_grant", "oidc_unauthorized"]);

function appendIfPresent(params: URLSearchParams, key: string, value: string | undefined) {
  if (value) params.set(key, value.slice(0, 1000));
}

export function loginDiagnosticsFromSearchParams(
  params: Pick<URLSearchParams, "get">
): LoginDiagnostics | null {
  const message = params.get("message") ?? undefined;
  const legacyError = params.get("error") ?? undefined;
  const detailCode = params.get("detailCode") ?? legacyError ?? undefined;
  const diagnostics: LoginDiagnostics = {
    message: message ?? (legacyError ? "oidc_callback_failed" : undefined),
    info: params.get("info") ?? undefined,
    detailCode,
    correlation: params.get("correlation") ?? undefined,
    rawDetail: params.get("rawDetail") ?? undefined
  };

  return Object.values(diagnostics).some(Boolean) ? diagnostics : null;
}

export function loginDiagnosticsFromRecord(
  params: Record<string, string | undefined>
): LoginDiagnostics | null {
  return loginDiagnosticsFromSearchParams({
    get: (key: string) => params[key] ?? null
  });
}

export function loginDiagnosticMessageKey(diagnostics: LoginDiagnostics): string {
  const code = diagnostics.detailCode ?? diagnostics.message ?? diagnostics.info;
  if (code && OIDC_FORBIDDEN_CODES.has(code)) return "oidc_error_forbidden";
  if (code && OIDC_UNAUTHORIZED_CODES.has(code)) return "oidc_error_unauthorized";
  return "oidc_error_generic";
}

export function buildLoginDiagnosticsUrl(
  pathname: "/login" | "/login/failed",
  origin: string,
  diagnostics: LoginDiagnostics
): URL {
  const url = new URL(pathname, origin);
  appendIfPresent(url.searchParams, "message", diagnostics.message);
  appendIfPresent(url.searchParams, "info", diagnostics.info);
  appendIfPresent(url.searchParams, "detailCode", diagnostics.detailCode);
  appendIfPresent(url.searchParams, "correlation", diagnostics.correlation);
  appendIfPresent(url.searchParams, "rawDetail", diagnostics.rawDetail);
  return url;
}

function recordValue(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)[key]
    : undefined;
}

function stringRecordValue(value: unknown, key: string): string | undefined {
  const field = recordValue(value, key);
  return typeof field === "string" ? field : undefined;
}

export function diagnosticsFromUnknownError(
  error: unknown,
  fallback: LoginDiagnostics = {}
): LoginDiagnostics {
  return {
    ...fallback,
    detailCode:
      stringRecordValue(error, "error") ??
      stringRecordValue(error, "code") ??
      stringRecordValue(recordValue(error, "cause"), "error") ??
      fallback.detailCode,
    rawDetail:
      stringRecordValue(error, "error_description") ??
      stringRecordValue(error, "message") ??
      stringRecordValue(recordValue(error, "cause"), "message") ??
      fallback.rawDetail
  };
}
