import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { pageTitle } from "@/lib/page-metadata";

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
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">{t("organisation_deactivated")}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">{t("access_disabled")}</CardContent>
        <CardFooter className="justify-end gap-2">
          <Button asChild variant="outline">
            {/* Plain <a>: /logout is a mutating route handler — keep Link
                prefetch away from it. */}
            <a href="/logout">{t("logout")}</a>
          </Button>
          <Button asChild>
            <a href={DEFAULT_LANDING}>{t("retry")}</a>
          </Button>
        </CardFooter>
      </Card>
    </main>
  );
}
