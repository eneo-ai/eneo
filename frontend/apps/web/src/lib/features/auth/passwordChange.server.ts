import {
  createZitadelClient,
  ZitadelRequestError,
  type ZitadelPasswordChangeCapability
} from "$lib/core/Zitadel";
import type { PasswordChangeCapability } from "./passwordChange";

type RequestContext = Readonly<{
  backendUrl?: string;
  eneoToken: string | null;
  zitadelUrl?: string;
  zitadelToken: string | null;
  fetch: typeof fetch;
}>;

type LocalPasswordChangeResponse = Readonly<{
  password_change?: unknown;
}>;

export type PasswordChangeFailure =
  | "current_password_incorrect"
  | "password_unchanged"
  | "policy_rejected"
  | "not_available"
  | "provider_rejected"
  | "rate_limited"
  | "request_failed";

export type PasswordChangeResult = "complete" | "session_invalidation_failed";

export class PasswordChangeRequestError extends Error {
  constructor(
    readonly reason: PasswordChangeFailure,
    readonly status: number
  ) {
    super(`Password change failed: ${reason}`);
    this.name = "PasswordChangeRequestError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function endpoint(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function normalizeZitadelCapability(
  capability: ZitadelPasswordChangeCapability
): PasswordChangeCapability {
  if (capability.source === "external") return capability;

  return {
    source: "zitadel",
    policy: {
      minLength: capability.policy.minLength,
      maxBytes: null,
      requiresUppercase: capability.policy.hasUppercase,
      requiresLowercase: capability.policy.hasLowercase,
      requiresNumber: capability.policy.hasNumber,
      requiresSymbol: capability.policy.hasSymbol
    }
  };
}

function normalizeEneoCapability(response: LocalPasswordChangeResponse): PasswordChangeCapability {
  if (!isRecord(response.password_change)) {
    return { source: "unavailable", policy: null };
  }

  const capability = response.password_change;
  if (capability.source === "external" && capability.policy === null) {
    return { source: "external", policy: null };
  }

  if (capability.source !== "eneo" || !isRecord(capability.policy)) {
    return { source: "unavailable", policy: null };
  }

  const minLength = capability.policy.min_length;
  const maxBytes = capability.policy.max_bytes;
  if (
    !Number.isSafeInteger(minLength) ||
    Number(minLength) < 1 ||
    !Number.isSafeInteger(maxBytes) ||
    Number(maxBytes) < 1
  ) {
    return { source: "unavailable", policy: null };
  }

  return {
    source: "eneo",
    policy: {
      minLength: Number(minLength),
      maxBytes: Number(maxBytes),
      requiresUppercase: false,
      requiresLowercase: false,
      requiresNumber: false,
      requiresSymbol: false
    }
  };
}

/**
 * Resolve the canonical password owner for this request. A provider access
 * token takes precedence because it proves this was a Zitadel login. Provider
 * failures are never interpreted as permission to mutate Eneo credentials.
 */
export async function discoverPasswordChangeCapability(
  context: RequestContext
): Promise<PasswordChangeCapability> {
  if (context.zitadelToken) {
    if (!context.zitadelUrl) return { source: "unavailable", policy: null };

    try {
      const zitadel = createZitadelClient(context.zitadelUrl, context.zitadelToken, context.fetch);
      return normalizeZitadelCapability(await zitadel.getPasswordChangeCapability());
    } catch {
      return { source: "unavailable", policy: null };
    }
  }

  if (!context.eneoToken || !context.backendUrl) {
    return { source: "unavailable", policy: null };
  }

  try {
    const response = await context.fetch(endpoint(context.backendUrl, "/api/v1/users/me/"), {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${context.eneoToken}`
      }
    });
    if (!response.ok) return { source: "unavailable", policy: null };

    const body: unknown = await response.json().catch(() => null);
    if (!isRecord(body)) return { source: "unavailable", policy: null };
    return normalizeEneoCapability(body);
  } catch {
    return { source: "unavailable", policy: null };
  }
}

function failureFromEneoResponse(status: number, body: unknown): PasswordChangeFailure {
  if (status === 429 && isRecord(body)) {
    const detail = body.detail;
    if (isRecord(detail) && detail.code === "rate_limit_exceeded") return "rate_limited";
  }

  const code = isRecord(body) ? body.eneo_error_code : undefined;
  switch (Number(code)) {
    case 9057:
      return "current_password_incorrect";
    case 9058:
      return "password_unchanged";
    case 9059:
      return "policy_rejected";
    case 9060:
      return "not_available";
    default:
      return "request_failed";
  }
}

async function changeEneoPassword(
  context: RequestContext,
  currentPassword: string,
  newPassword: string
): Promise<PasswordChangeResult> {
  if (!context.backendUrl || !context.eneoToken) {
    throw new PasswordChangeRequestError("not_available", 401);
  }

  const response = await context.fetch(endpoint(context.backendUrl, "/api/v1/users/me/password/"), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${context.eneoToken}`
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword
    })
  });
  if (response.ok) return "complete";

  const body: unknown = await response.json().catch(() => null);
  throw new PasswordChangeRequestError(
    failureFromEneoResponse(response.status, body),
    response.status
  );
}

async function invalidateEneoSessions(context: RequestContext): Promise<boolean> {
  if (!context.backendUrl || !context.eneoToken) return false;

  try {
    const response = await context.fetch(
      endpoint(context.backendUrl, "/api/v1/users/me/sessions/invalidate/"),
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${context.eneoToken}`
        }
      }
    );
    if (response.ok) return true;
    console.warn("Eneo session invalidation failed after provider password change", {
      status: response.status
    });
  } catch {
    // The provider mutation has already succeeded and cannot be rolled back.
    // The caller still clears this browser's cookies and reports success.
    console.warn("Eneo session invalidation was unreachable after provider password change");
  }
  return false;
}

async function changeZitadelPassword(
  context: RequestContext,
  currentPassword: string,
  newPassword: string
): Promise<PasswordChangeResult> {
  if (!context.zitadelUrl || !context.zitadelToken) {
    throw new PasswordChangeRequestError("not_available", 401);
  }

  try {
    const zitadel = createZitadelClient(context.zitadelUrl, context.zitadelToken, context.fetch);
    await zitadel.updatePassword(currentPassword, newPassword);
  } catch (error) {
    if (error instanceof ZitadelRequestError) {
      const reason =
        error.status === 400
          ? "provider_rejected"
          : error.status === 429
            ? "rate_limited"
            : "request_failed";
      throw new PasswordChangeRequestError(reason, error.status);
    }
    throw new PasswordChangeRequestError("request_failed", 502);
  }

  return (await invalidateEneoSessions(context)) ? "complete" : "session_invalidation_failed";
}

export async function changePassword(
  context: RequestContext,
  capability: PasswordChangeCapability,
  currentPassword: string,
  newPassword: string
): Promise<PasswordChangeResult> {
  if (capability.source === "eneo") {
    return changeEneoPassword(context, currentPassword, newPassword);
  }
  if (capability.source === "zitadel") {
    return changeZitadelPassword(context, currentPassword, newPassword);
  }
  throw new PasswordChangeRequestError("not_available", 409);
}
