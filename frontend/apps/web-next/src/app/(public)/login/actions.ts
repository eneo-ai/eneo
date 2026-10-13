"use server";

import { redirect } from "next/navigation";
import { passwordLogin } from "@/lib/auth/password";
import { safeNextPath } from "@/lib/auth/safe-next";
import { setSessionCookie } from "@/lib/auth/session";

export interface LoginFormState {
  error?:
    "invalid_credentials" | "too_many_attempts" | "deactivated" | "unavailable" | "missing_fields";
  /** What the user typed, so the form can keep it after a failed attempt. */
  email?: string;
  /** Failed attempts left before the account is blocked, when the backend said. */
  attemptsRemaining?: number | null;
  /** How long the account stays blocked, in seconds, when the backend said. */
  retryAfterSeconds?: number | null;
}

export async function loginAction(
  _previous: LoginFormState,
  formData: FormData
): Promise<LoginFormState> {
  const email = formData.get("email");
  const password = formData.get("password");
  const next = formData.get("next");

  if (typeof email !== "string" || typeof password !== "string" || !email || !password) {
    return { error: "missing_fields", email: typeof email === "string" ? email : undefined };
  }

  const result = await passwordLogin(email, password);
  if (!result.ok) {
    if (result.error === "deactivated") redirect("/deactivated");
    return {
      error: result.error,
      email,
      attemptsRemaining: result.limit?.attemptsRemaining ?? null,
      retryAfterSeconds: result.limit?.retryAfterSeconds ?? null
    };
  }

  await setSessionCookie(result.session);
  redirect(safeNextPath(typeof next === "string" ? next : null));
}
