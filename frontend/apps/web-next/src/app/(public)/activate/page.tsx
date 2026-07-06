import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { getSession } from "@/lib/auth/session";
import { pageTitle } from "@/lib/page-metadata";
import { provisionUser } from "./actions";

export const generateMetadata = pageTitle("activate");

/**
 * Landing for OIDC users whose account isn't provisioned yet (backend 9006).
 * The backend auto-provisions on login when the tenant allows it; landing here
 * means that didn't happen, so we offer manual provisioning — which succeeds
 * once an admin has created an invitation for the user's email address.
 */
export default async function ActivatePage({
  searchParams
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (!(await getSession())) redirect("/login");

  const { error } = await searchParams;
  const t = await getTranslations();

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">{t("almost_there")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{t("activation_failed")}</AlertDescription>
            </Alert>
          )}
          <p className="text-muted-foreground text-sm">{t("account_not_activated")}</p>
        </CardContent>
        <CardFooter className="justify-end gap-2">
          <Button asChild variant="outline">
            {/* Plain <a>: /logout is a mutating route handler — keep Link
                prefetch away from it. */}
            <a href="/logout">{t("logout")}</a>
          </Button>
          <form action={provisionUser}>
            <Button type="submit">{t("activate")}</Button>
          </form>
        </CardFooter>
      </Card>
    </main>
  );
}
