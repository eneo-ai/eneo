import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { loginDiagnosticsFromRecord } from "@/lib/auth/login-diagnostics";
import { pageTitle } from "@/lib/page-metadata";
import { PublicPage } from "../../public-page";
import { LoginDiagnosticsAlert } from "../login-diagnostics-alert";

export const generateMetadata = pageTitle("login_failed");

export default async function LoginFailedPage({
  searchParams
}: {
  searchParams: Promise<{
    message?: string;
    info?: string;
    detailCode?: string;
    correlation?: string;
    rawDetail?: string;
  }>;
}) {
  const t = await getTranslations();
  const diagnostics = loginDiagnosticsFromRecord(await searchParams);

  return (
    <PublicPage title={t("login_failed")}>
      {diagnostics ? (
        <LoginDiagnosticsAlert diagnostics={diagnostics} t={t} />
      ) : (
        <p className="text-muted-foreground text-sm">{t("failed_to_login")}</p>
      )}
      <Button asChild variant="outline">
        <a href="/login">{t("try_logging_in_again")}</a>
      </Button>
    </PublicPage>
  );
}
