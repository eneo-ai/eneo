import { errorCodeFromResponse } from "@/lib/api/errors";
import { readAttemptLimit, type LoginAttemptLimit } from "@/lib/auth/login-attempt-limit";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";

export type LoginFormState = Partial<LoginAttemptLimit> & {
  error?:
    "missing_fields" | "invalid_credentials" | "too_many_attempts" | "deactivated" | "unavailable";
  email?: string;
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

  if (response.status === 401 || response.status === 429) {
    return {
      error: response.status === 401 ? "invalid_credentials" : "too_many_attempts",
      email,
      ...(await readAttemptLimit(response))
    };
  }
  if (response.status === 403) {
    const code = await errorCodeFromResponse(response);
    return { error: code === 9019 || code === 9025 ? "deactivated" : "unavailable", email };
  }
  if (!response.ok) return { error: "unavailable", email };

  navigateTo(safeNextPath(next));
  return {};
}
