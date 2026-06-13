import { getTranslations } from "next-intl/server";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("organisation_deactivated");

export default async function DeactivatedPage() {
  const t = await getTranslations();

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">{t("account")}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">{t("access_disabled")}</CardContent>
      </Card>
    </main>
  );
}
