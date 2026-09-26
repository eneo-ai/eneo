import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getSession } from "@/lib/auth/session";
import { pageTitle } from "@/lib/page-metadata";
import { PublicPage } from "../public-page";
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
    <PublicPage
      title={t("almost_there")}
      width="md"
      footer={
        <>
          <Button asChild variant="outline">
            {/* Plain <a>: /logout is a mutating route handler — keep Link
                prefetch away from it. */}
            <a href="/logout">{t("logout")}</a>
          </Button>
          <form action={provisionUser}>
            <Button type="submit">{t("activate")}</Button>
          </form>
        </>
      }
    >
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{t("activation_failed")}</AlertDescription>
        </Alert>
      )}
      <p className="text-muted-foreground text-sm">{t("account_not_activated")}</p>
    </PublicPage>
  );
}
