import { getTranslations } from "next-intl/server";

export default async function DashboardPage() {
  const t = await getTranslations();

  return <h1 className="text-2xl font-semibold">{t("dashboard")}</h1>;
}
