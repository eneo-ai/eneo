"use server";

import { redirect } from "next/navigation";
import { eneoApi } from "@/lib/api/server";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { getAccessTokenOrNull } from "@/lib/auth/session";

/**
 * Attempts to provision the logged-in (at the IdP) but not-yet-created user.
 * The endpoint takes the IdP access token in the body (the field is named
 * zitadel_token for legacy reasons). The eneoApi 401 interceptor deliberately
 * skips this endpoint so a rejected provisioning lands back here instead of
 * looping through /activate.
 */
export async function provisionUser(): Promise<void> {
  const token = await getAccessTokenOrNull();
  if (!token) redirect("/login");

  const { response } = await eneoApi().POST("/api/v1/users/provision/", {
    body: { zitadel_token: token }
  });
  if (response.ok) redirect(DEFAULT_LANDING);
  redirect("/activate?error=1");
}
