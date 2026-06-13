import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("login_failed");

export default async function LoginFailedPage() {
  const t = await getTranslations();

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{t("login_failed")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline">
            <a href="/login">{t("login")}</a>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
