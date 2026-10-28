import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import { PageBar } from "@/components/shell/page-bar";
import { pageTitle } from "@/lib/page-metadata";
import { WhatsNewPage } from "@/features/whats-new/whats-new-page";

export const generateMetadata = pageTitle("whats_new");

export default async function WhatsNewRoute() {
  const settings = await unwrap(eneoApi().GET("/api/v1/settings/"));
  if (settings.whats_new_enabled === false) redirect("/");
  const t = await getTranslations();
  // Below 1024 px a screen pushed from Konto, where Nyheter is listed (decisions 20, 22).
  return (
    <>
      <PageBar parent={{ label: t("account"), href: "/account" }} title={t("whats_new")} />
      <WhatsNewPage title={t("whats_new")} />
    </>
  );
}
