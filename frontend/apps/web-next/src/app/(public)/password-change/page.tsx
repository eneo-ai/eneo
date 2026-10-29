import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ChangePasswordForm } from "@/features/account/change-password";
import { passwordCapability } from "@/features/auth/password-policy";
import { passwordChangedLogoutUrl } from "@/lib/auth/password-change-path";
import { safeNextPath } from "@/lib/auth/safe-next";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { pageTitle } from "@/lib/page-metadata";
import type { Schema } from "@/lib/api/models";
import { PublicPage } from "../public-page";

export const generateMetadata = pageTitle("password_change_required_title");

/**
 * Where a password session lands when its local password is one-time (set
 * by an administrator or the deployment seed) or has expired under the
 * organisation's policy: the backend answers every other endpoint with
 * 403/9070 until the password is replaced, and both API clients send such a
 * session here. Outside the app shell on purpose: the shell's own loads are
 * among the refused ones. The form signs the browser out on success, and the
 * user signs in again with the password they chose and lands on `next`.
 */
export default async function PasswordChangePage({
  searchParams
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  const token = await getAccessTokenOrNull();
  if (!token) {
    const resume = next ? `/password-change?next=${encodeURIComponent(next)}` : "/password-change";
    redirect(`/login?next=${encodeURIComponent(resume)}`);
  }

  // Raw fetch on purpose: eneoApi's interceptor would redirect a refusal
  // right back here in a loop, and /users/me/ is one of the reachable routes.
  let me: Schema<"UserPublic"> | null = null;
  let sessionRejected = false;
  try {
    const response = await fetch(`${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/api/v1/users/me/`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store"
    });
    sessionRejected = response.status === 401;
    if (response.ok) me = (await response.json()) as Schema<"UserPublic">;
  } catch {
    // Backend unreachable: fall through to the unavailable message.
  }
  // Next redirects throw: keep session recovery outside the fetch catch.
  if (sessionRejected) redirect("/logout?reason=expired");
  if (me && !me.password_status?.change_required) redirect(safeNextPath(next));

  const t = await getTranslations();
  const capability = me ? passwordCapability(me.password_change) : null;
  const reason = me?.password_status?.reason;

  return (
    <PublicPage
      title={t("password_change_required_title")}
      description={
        reason === "expired"
          ? t("password_change_required_expired")
          : t("password_change_required_admin_set")
      }
      width="md"
      footer={
        <Button asChild variant="outline">
          {/* Plain <a>: /logout is a mutating route handler — keep Link
              prefetch away from it. */}
          <a href="/logout">{t("logout")}</a>
        </Button>
      }
    >
      {me && capability?.source === "eneo" ? (
        <ChangePasswordForm
          policy={capability.policy}
          email={me.email}
          currentPasswordHint={
            // "Just signed in with" only fits a one-time password; an expired
            // one may belong to a session that started days ago.
            reason === "expired"
              ? t("password_change_required_expired_current_hint")
              : t("password_change_required_current_hint")
          }
          afterChangeHref={passwordChangedLogoutUrl(next)}
        />
      ) : (
        <p className="text-muted-foreground text-sm">{t("password_change_not_available")}</p>
      )}
    </PublicPage>
  );
}
