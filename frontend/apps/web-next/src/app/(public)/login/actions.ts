"use server";

import { redirect } from "next/navigation";
import { passwordLogin } from "@/lib/auth/password";
import { safeNextPath } from "@/lib/auth/safe-next";
import { setSessionCookie } from "@/lib/auth/session";

export interface LoginFormState {
  error?: "invalid_credentials" | "deactivated" | "unavailable" | "missing_fields";
  /** What the user typed, so the form can keep it after a failed attempt. */
  email?: string;
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
    return { error: result.error, email };
  }

  await setSessionCookie(result.session);
  redirect(safeNextPath(typeof next === "string" ? next : null));
}
