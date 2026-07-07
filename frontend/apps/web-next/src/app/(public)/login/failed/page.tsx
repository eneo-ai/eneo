import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { loginDiagnosticsFromRecord } from "@/lib/auth/login-diagnostics";
import { pageTitle } from "@/lib/page-metadata";
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
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{t("login_failed")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {diagnostics ? (
            <LoginDiagnosticsAlert diagnostics={diagnostics} t={t} />
          ) : (
            <p className="text-muted-foreground text-sm">{t("failed_to_login")}</p>
          )}
          <Button asChild variant="outline">
            <a href="/login">{t("try_logging_in_again")}</a>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
