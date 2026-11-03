import { errorCodeFromResponse, extractTraceId } from "@/lib/api/errors";
import { readAttemptLimit, type LoginAttemptLimit } from "@/lib/auth/login-attempt-limit";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";

export type LoginFormState = Partial<LoginAttemptLimit> & {
  error?:
    "missing_fields" | "invalid_credentials" | "too_many_attempts" | "deactivated" | "unavailable";
  email?: string;
  traceId?: string;
};

export async function submitPasswordLogin(
  next: string | undefined,
  _previous: LoginFormState,
  form: FormData
): Promise<LoginFormState> {
  const email = form.get("email");
  const password = form.get("password");
  if (typeof email !== "string" || !email || typeof password !== "string" || !password) {
    return { error: "missing_fields", email: typeof email === "string" ? email : undefined };
  }

  let response: Response;
  try {
    // This establishes a new identity; the backend sets its HttpOnly cookie.
    response = await fetch("/api/v1/auth/session/password/", {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      body: new URLSearchParams({ username: email, password })
    });
  } catch {
    return { error: "unavailable", email };
  }

  // The id support needs to find a failed attempt in the backend log.
  const traceId = extractTraceId(response.headers);
  // 422 is a form the backend refused (a malformed email): the user's input, as 401.
  if (response.status === 401 || response.status === 422 || response.status === 429) {
    return {
      error: response.status === 429 ? "too_many_attempts" : "invalid_credentials",
      email,
      traceId,
      ...(await readAttemptLimit(response))
    };
  }
  if (response.status === 403) {
    const code = await errorCodeFromResponse(response);
    return {
      error: code === 9019 || code === 9025 ? "deactivated" : "unavailable",
      email,
      traceId
    };
  }
  if (!response.ok) return { error: "unavailable", email, traceId };

  navigateTo(safeNextPath(next));
  return {};
}
