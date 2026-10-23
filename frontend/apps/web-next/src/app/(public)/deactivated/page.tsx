import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Button } from "@/components/ui/button";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { pageTitle } from "@/lib/page-metadata";
import { PublicPage } from "../public-page";

export const generateMetadata = pageTitle("organisation_deactivated");

/** Landing for suspended tenants (backend 403/9025). Self-heals: when the
 * organisation is active again the user is sent straight back into the app. */
export default async function DeactivatedPage() {
  const token = await getAccessTokenOrNull();
  if (!token) redirect("/login");

  // Raw fetch on purpose: eneoApi's suspension interceptor would redirect a
  // still-suspended tenant right back here in a loop.
  let healed = false;
  try {
    const me = await fetch(`${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/api/v1/users/me/`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store"
    });
    healed = me.ok;
  } catch {
    // Backend unreachable: keep showing the page.
  }
  if (healed) redirect(DEFAULT_LANDING);

  const t = await getTranslations();

  return (
    <PublicPage
      title={t("organisation_deactivated")}
      width="md"
      footer={
        <>
          <Button asChild variant="outline">
            {/* Plain <a>: /logout is a mutating route handler — keep Link
                prefetch away from it. */}
            <a href="/logout">{t("logout")}</a>
          </Button>
          <Button asChild>
            <a href={DEFAULT_LANDING}>{t("retry")}</a>
          </Button>
        </>
      }
    >
      <p className="text-muted-foreground text-sm">{t("access_disabled")}</p>
    </PublicPage>
  );
}
