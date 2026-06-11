import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isOidcEnabled } from "@/lib/auth/oidc";
import { getSession } from "@/lib/auth/session";
import { LoginForm } from "./login-form";

export default async function LoginPage({
  searchParams
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  if (await getSession()) redirect("/dashboard");

  const { next, error } = await searchParams;
  const t = await getTranslations();
  const oidc = isOidcEnabled();

  const loginHref = next ? `/auth/login?next=${encodeURIComponent(next)}` : "/auth/login";

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{t("welcome")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error === "access_denied" && (
            <Alert variant="destructive">
              <AlertDescription>{t("login_failed")}</AlertDescription>
            </Alert>
          )}
          {oidc && (
            <>
              <Button asChild variant="default">
                <a href={loginHref}>{t("login_with_sso")}</a>
              </Button>
              <div className="text-muted-foreground text-center text-xs uppercase">{t("or")}</div>
            </>
          )}
          <LoginForm next={next} />
        </CardContent>
      </Card>
    </main>
  );
}
