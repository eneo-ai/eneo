import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("activate");

/**
 * Landing for OIDC users whose account isn't provisioned yet. In the generic-OIDC
 * model the backend auto-provisions on login when allowed; reaching here means
 * provisioning was rejected (no invitation / disallowed domain), so we ask the
 * user to get an admin invitation and retry.
 */
export default async function ActivatePage() {
  const t = await getTranslations();

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">{t("almost_there")}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          {t("account_not_activated")}
        </CardContent>
        <CardFooter className="justify-end gap-2">
          <Button asChild variant="outline">
            <Link href="/logout">{t("logout")}</Link>
          </Button>
          <Button asChild>
            <Link href="/login">{t("retry")}</Link>
          </Button>
        </CardFooter>
      </Card>
    </main>
  );
}
